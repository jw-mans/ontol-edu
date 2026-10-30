# Парсер TDL → AST
from __future__ import annotations

from typing import List, Optional

from .tdl_ast import (
    AlignCmd,
    AssociationClassDecl,
    AssocEnd,
    AssociationDecl,
    AttributeLine,
    BindCmd,
    ClassDecl,
    DataTypeDecl,
    DependencyDecl,
    DistributeCmd,
    Document,
    EnumDecl,
    FixCmd,
    GeneralizationDecl,
    InterfaceDecl,
    LayoutBlock,
    OperationLine,
    ParameterLine,
    RealizationDecl,
    TemplateBindingDecl,
    TemplateDecl,
)
from .tdl_lexer import Token, TokenKind


class ParseError(Exception):
    def __init__(self, msg: str, token: Optional[Token] = None):
        if token:
            msg = f"{msg} (строка {token.line}, столбец {token.column})"
        super().__init__(msg)


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        if self.pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.pos]

    def advance(self) -> Token:
        t = self.peek()
        if self.pos < len(self.tokens):
            self.pos += 1
        return t

    def at(self, kind: TokenKind) -> bool:
        return self.peek().kind == kind

    def expect(self, kind: TokenKind) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise ParseError(f"Ожидался {kind.name}, получен {t.kind.name}", t)
        return self.advance()

    def _ident_or_keyword(self) -> str:
        """Идентификатор или ключевое слово, допустимое как имя (имя, в, как и т.д.)."""
        t = self.peek()
        if t.kind == TokenKind.IDENT:
            self.advance()
            return t.value or ""
        for kind, literal in [
            (TokenKind.ИМЯ, "имя"),
            (TokenKind.В, "в"),
            (TokenKind.КАК, "как"),
        ]:
            if t.kind == kind:
                self.advance()
                return literal
        raise ParseError(f"Ожидался идентификатор, получен {t.kind.name}", t)

    def expect_ident(self) -> str:
        return self._ident_or_keyword()

    def _visibility(self) -> Optional[str]:
        if self.at(TokenKind.PLUS):
            self.advance()
            return "+"
        if self.at(TokenKind.MINUS):
            self.advance()
            return "-"
        if self.at(TokenKind.HASH):
            self.advance()
            return "#"
        if self.at(TokenKind.TILDE):
            self.advance()
            return "~"
        return None

    def _multiplicity_str(self) -> Optional[str]:
        if self.at(TokenKind.LBRACKET):
            self.advance()
            if self.at(TokenKind.NUMBER):
                lo = self.advance().value or "0"
                if self.at(TokenKind.DOTDOT):
                    self.advance()
                    if self.at(TokenKind.STAR):
                        self.advance()
                        mult = f"{lo}..*"
                    elif self.at(TokenKind.NUMBER):
                        hi = self.advance().value or "0"
                        mult = f"{lo}..{hi}"
                    else:
                        raise ParseError("Ожидалось * или число после ..", self.peek())
                else:
                    mult = lo
                self.expect(TokenKind.RBRACKET)
                return mult
            if self.at(TokenKind.STAR):
                self.advance()
                self.expect(TokenKind.RBRACKET)
                return "*"
            self.expect(TokenKind.RBRACKET)
            return None
        return None

    def _parse_attribute_line(self) -> AttributeLine:
        vis = self._visibility()
        name = self._ident_or_keyword()
        mult = self._multiplicity_str()
        type_ = None
        default = None
        only_read = False
        if self.at(TokenKind.COLON):
            self.advance()
            type_ = self.expect_ident()
        if self.at(TokenKind.EQUALS):
            self.advance()
            if self.at(TokenKind.NUMBER):
                default = self.advance().value
            elif self.at(TokenKind.STRING):
                default = self.advance().value
            else:
                default = self.expect_ident()
        if self.at(TokenKind.LBRACE):
            self.advance()
            if self.at(TokenKind.ТОЛЬКО_ЧТЕНИЕ):
                self.advance()
                only_read = True
            while self.at(TokenKind.COMMA) or self.at(TokenKind.ТОЛЬКО_ЧТЕНИЕ):
                if self.at(TokenKind.COMMA):
                    self.advance()
                if self.at(TokenKind.ТОЛЬКО_ЧТЕНИЕ):
                    self.advance()
                    only_read = True
            self.expect(TokenKind.RBRACE)
        return AttributeLine(
            visibility=vis,
            name=name,
            multiplicity=mult,
            type_=type_,
            default=default,
            only_read=only_read,
        )

    def _parse_parameter_line(self) -> ParameterLine:
        name = self.expect_ident()
        type_ = None
        default = None

        if self.at(TokenKind.COLON):
            self.advance()
            type_ = self.expect_ident()

        if self.at(TokenKind.EQUALS):
            self.advance()
            if self.at(TokenKind.NUMBER):
                default = self.advance().value
            elif self.at(TokenKind.STRING):
                default = self.advance().value
            else:
                default = self.expect_ident()

        return ParameterLine(name=name, type_=type_, default=default)

    def _parse_operation_line(self) -> OperationLine:
        vis = self._visibility()
        name = self.expect_ident()
        params: List[ParameterLine] = []
        self.expect(TokenKind.LPAREN)
        if not self.at(TokenKind.RPAREN):
            while True:
                params.append(self._parse_parameter_line())

                if not self.at(TokenKind.COMMA):
                    break
                self.advance()
        self.expect(TokenKind.RPAREN)
        return_type = None
        if self.at(TokenKind.COLON):
            self.advance()
            return_type = self.expect_ident()
        is_abstract = False
        is_query = False
        is_leaf = False
        if self.at(TokenKind.LBRACE):
            self.advance()
            while True:
                if self.at(TokenKind.АБСТРАКТНАЯ):
                    self.advance()
                    is_abstract = True
                elif self.at(TokenKind.ЗАПРОС):
                    self.advance()
                    is_query = True
                elif self.at(TokenKind.ЛИСТ):
                    self.advance()
                    is_leaf = True
                elif self.at(TokenKind.COMMA):
                    self.advance()
                else:
                    break
            self.expect(TokenKind.RBRACE)
        return OperationLine(
            visibility=vis,
            name=name,
            params=params,
            return_type=return_type,
            is_abstract=is_abstract,
            is_query=is_query,
            is_leaf=is_leaf,
        )

    def _parse_class_members(self) -> tuple[List[AttributeLine], List[OperationLine]]:
        attrs: List[AttributeLine] = []
        ops: List[OperationLine] = []
        if self.at(TokenKind.АТРИБУТЫ):
            self.advance()
            while self.at(TokenKind.PLUS) or self.at(TokenKind.MINUS) or self.at(TokenKind.HASH) or self.at(TokenKind.TILDE) or self.at(TokenKind.IDENT):
                attrs.append(self._parse_attribute_line())
        if self.at(TokenKind.ОПЕРАЦИИ):
            self.advance()
            while self.at(TokenKind.PLUS) or self.at(TokenKind.MINUS) or self.at(TokenKind.HASH) or self.at(TokenKind.TILDE) or self.at(TokenKind.IDENT):
                ops.append(self._parse_operation_line())
        return attrs, ops

    def _parse_class(self) -> ClassDecl:
        self.expect(TokenKind.КЛАСС)
        name = self.expect_ident()
        is_abstract = False
        if self.at(TokenKind.АБСТРАКТНЫЙ):
            self.advance()
            is_abstract = True
        attrs, ops = self._parse_class_members()
        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.КЛАСС)
        return ClassDecl(name=name, is_abstract=is_abstract, attributes=attrs, operations=ops)

    def _parse_interface(self) -> InterfaceDecl:
        self.expect(TokenKind.ИНТЕРФЕЙС)
        name = self.expect_ident()
        attrs, ops = self._parse_class_members()
        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.ИНТЕРФЕЙС)
        return InterfaceDecl(name=name, attributes=attrs, operations=ops)

    def _parse_data_type(self) -> DataTypeDecl:
        self.expect(TokenKind.ТИП_ДАННЫХ)
        name = self.expect_ident()
        attrs, ops = self._parse_class_members()
        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.ТИП_ДАННЫХ)
        return DataTypeDecl(name=name, attributes=attrs, operations=ops)

    def _parse_template(self) -> TemplateDecl:
        self.expect(TokenKind.ШАБЛОН)
        name = self.expect_ident()
        template_parameters: List[ParameterLine] = []

        if self.at(TokenKind.ПАРАМЕТРЫ):
            self.advance()
            while self.peek().kind in (
                TokenKind.IDENT,
                TokenKind.ИМЯ,
                TokenKind.В,
                TokenKind.КАК,
            ):
                template_parameters.append(self._parse_parameter_line())

        attrs, ops = self._parse_class_members()
        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.ШАБЛОН)
        return TemplateDecl(
            name=name,
            template_parameters=template_parameters,
            attributes=attrs,
            operations=ops,
        )

    def _parse_template_binding(self) -> TemplateBindingDecl:
        self.expect(TokenKind.ПОДСТАНОВКА)
        bound_element = self.expect_ident()
        self.expect(TokenKind.ARROW)
        template = self.expect_ident()
        substitutions: List[ParameterLine] = []

        self.expect(TokenKind.LBRACE)
        while not self.at(TokenKind.RBRACE):
            if self.at(TokenKind.EOF):
                raise ParseError("Ожидалась } в ПОДСТАНОВКА", self.peek())

            substitution = self._parse_parameter_line()
            if substitution.default is None:
                raise ParseError("Ожидалась подстановка вида T = Actual", self.peek())
            substitutions.append(substitution)

            if not self.at(TokenKind.COMMA):
                break
            self.advance()
        self.expect(TokenKind.RBRACE)

        return TemplateBindingDecl(
            bound_element=bound_element,
            template=template,
            substitutions=substitutions,
        )

    def _parse_generalization(self) -> GeneralizationDecl:
        self.expect(TokenKind.ОБОБЩЕНИЕ)
        specific = self.expect_ident()
        self.expect(TokenKind.ARROW)
        general = self.expect_ident()
        substitutable = True
        if self.at(TokenKind.ПОДСТАНОВОЧНОЕ):
            self.advance()
            substitutable = True
        return GeneralizationDecl(specific=specific, general=general, substitutable=substitutable)

    def _parse_dependency(self) -> DependencyDecl:
        self.expect(TokenKind.ЗАВИСИМОСТЬ)
        client = self.expect_ident()
        self.expect(TokenKind.ARROW)
        supplier = self.expect_ident()
        stereotype = None
        if self.at(TokenKind.STRING):
            stereotype = self.advance().value
        elif self.at(TokenKind.IDENT):
            stereotype = self.advance().value
        return DependencyDecl(client=client, supplier=supplier, stereotype=stereotype)

    def _parse_realization(self) -> RealizationDecl:
        self.expect(TokenKind.РЕАЛИЗАЦИЯ)
        implementer = self.expect_ident()
        self.expect(TokenKind.ARROW)
        interface = self.expect_ident()
        return RealizationDecl(implementer=implementer, interface=interface)

    def _parse_assoc_end(self) -> AssocEnd:
        participant = self.expect_ident()
        mult = self._multiplicity_str()
        if mult is None and self.at(TokenKind.NUMBER):
            mult = self.advance().value
        if mult is None and self.at(TokenKind.STAR):
            self.advance()
            mult = "*"
        role = None
        if self.at(TokenKind.COLON):
            self.advance()
            role = self._ident_or_keyword()
        return AssocEnd(participant=participant, multiplicity=mult, role=role)

    def _parse_association_like(self, aggregation: Optional[str] = None) -> AssociationDecl:
        end1 = self._parse_assoc_end()
        self.expect(TokenKind.DASH)
        end2 = self._parse_assoc_end()

        name = None
        is_derived = False

        while self.at(TokenKind.ИМЯ) or self.at(TokenKind.ПРОИЗВОДНАЯ):
            if self.at(TokenKind.ИМЯ):
                self.advance()
                if self.at(TokenKind.STRING):
                    name = self.advance().value
                else:
                    name = self.expect_ident()
            elif self.at(TokenKind.ПРОИЗВОДНАЯ):
                self.advance()
                is_derived = True

        return AssociationDecl(
            end1=end1,
            end2=end2,
            name=name,
            is_derived=is_derived,
            aggregation=aggregation,
        )

    def _parse_association(self) -> AssociationDecl:
        self.expect(TokenKind.АССОЦИАЦИЯ)
        return self._parse_association_like()

    def _parse_composition(self) -> AssociationDecl:
        self.expect(TokenKind.КОМПОЗИЦИЯ)
        return self._parse_association_like(aggregation="composition")

    def _parse_aggregation(self) -> AssociationDecl:
        self.expect(TokenKind.АГРЕГАЦИЯ)
        return self._parse_association_like(aggregation="aggregation")

    def _parse_association_class(self) -> AssociationClassDecl:
        self.expect(TokenKind.КЛАСС_АССОЦИАЦИИ)
        name = self.expect_ident()

        if not self.at(TokenKind.АССОЦИАЦИЯ):
            raise ParseError("Ожидалась АССОЦИАЦИЯ внутри КЛАСС_АССОЦИАЦИИ", self.peek())

        association = self._parse_association()
        attrs, ops = self._parse_class_members()
        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.КЛАСС_АССОЦИАЦИИ)
        return AssociationClassDecl(
            name=name,
            association=association,
            attributes=attrs,
            operations=ops,
        )

    def _parse_enum(self) -> EnumDecl:
        self.expect(TokenKind.ПЕРЕЧИСЛЕНИЕ)
        name = self.expect_ident()

        literals: List[str] = []

        while not self.at(TokenKind.КОНЕЦ):
            if self.at(TokenKind.EOF):
                raise ParseError("Ожидался КОНЕЦ ПЕРЕЧИСЛЕНИЕ", self.peek())

            if self.at(TokenKind.IDENT):
                literals.append(self.advance().value or "")
                continue

            literals.append(self._ident_or_keyword())

        self.expect(TokenKind.КОНЕЦ)
        self.expect(TokenKind.ПЕРЕЧИСЛЕНИЕ)

        return EnumDecl(name=name, literals=literals)

    def _parse_layout_commands(self) -> LayoutBlock:
        commands: list = []
        while not self.at(TokenKind.КОНЕЦ):
            if self.at(TokenKind.EOF):
                raise ParseError("Ожидался КОНЕЦ РАЗМЕЩЕНИЕ", self.peek())
            if self.at(TokenKind.ВЫРОВНЯТЬ):
                self.advance()
                self.expect(TokenKind.ПО)
                where = self.advance().kind.name
                if where not in ("ЛЕВОМУ", "ПРАВОМУ", "ВЕРХУ", "НИЗУ"):
                    raise ParseError("Ожидалось ЛЕВОМУ/ПРАВОМУ/ВЕРХУ/НИЗУ", self.peek())
                elts = []
                while self.at(TokenKind.IDENT):
                    elts.append(self.advance().value or "")
                commands.append(AlignCmd(where=where, elements=elts))
                continue
            if self.at(TokenKind.РАСПРЕДЕЛИТЬ):
                self.advance()
                self.expect(TokenKind.ПО)
                axis = self.advance().kind.name
                if axis not in ("ГОРИЗОНТАЛИ", "ВЕРТИКАЛИ"):
                    raise ParseError("Ожидалось ГОРИЗОНТАЛИ/ВЕРТИКАЛИ", self.peek())
                elts = []
                while self.at(TokenKind.IDENT):
                    elts.append(self.advance().value or "")
                step = None
                if self.at(TokenKind.ШАГ):
                    self.advance()
                    step = int(self.expect(TokenKind.NUMBER).value or "0")
                commands.append(DistributeCmd(axis=axis, elements=elts, step=step))
                continue
            if self.at(TokenKind.ЗАФИКСИРОВАТЬ):
                self.advance()
                elem = self.expect_ident()
                self.expect(TokenKind.В)
                self.expect(TokenKind.LPAREN)
                x = float(self.expect(TokenKind.NUMBER).value or "0")
                self.expect(TokenKind.COMMA)
                y = float(self.expect(TokenKind.NUMBER).value or "0")
                self.expect(TokenKind.RPAREN)
                commands.append(FixCmd(element=elem, x=x, y=y))
                continue
            if self.at(TokenKind.ПРИВЯЗАТЬ):
                self.advance()
                elem1 = self.expect_ident()
                dir_t = self.advance()
                if dir_t.kind not in (TokenKind.ЛЕВЕЕ, TokenKind.ПРАВЕЕ, TokenKind.ВЫШЕ, TokenKind.НИЖЕ):
                    raise ParseError("Ожидалось ЛЕВЕЕ/ПРАВЕЕ/ВЫШЕ/НИЖЕ", dir_t)
                direction = dir_t.kind.name
                elem2 = self.expect_ident()
                commands.append(BindCmd(elem1=elem1, direction=direction, elem2=elem2))
                continue
            self.advance()
        return LayoutBlock(commands=commands)

    def parse(self) -> Document:
        doc = Document()
        while not self.at(TokenKind.EOF):
            if self.at(TokenKind.РАЗМЕЩЕНИЕ):
                self.advance()
                doc.layout = self._parse_layout_commands()
                self.expect(TokenKind.КОНЕЦ)
                self.expect(TokenKind.РАЗМЕЩЕНИЕ)
                break
            if self.at(TokenKind.КЛАСС):
                doc.declarations.append(self._parse_class())
            elif self.at(TokenKind.ИНТЕРФЕЙС):
                doc.declarations.append(self._parse_interface())
            elif self.at(TokenKind.ТИП_ДАННЫХ):
                doc.declarations.append(self._parse_data_type())
            elif self.at(TokenKind.ШАБЛОН):
                doc.declarations.append(self._parse_template())
            elif self.at(TokenKind.ПОДСТАНОВКА):
                doc.declarations.append(self._parse_template_binding())
            elif self.at(TokenKind.ПЕРЕЧИСЛЕНИЕ):
                doc.declarations.append(self._parse_enum())
            elif self.at(TokenKind.ОБОБЩЕНИЕ):
                doc.declarations.append(self._parse_generalization())
            elif self.at(TokenKind.ЗАВИСИМОСТЬ):
                doc.declarations.append(self._parse_dependency())
            elif self.at(TokenKind.РЕАЛИЗАЦИЯ):
                doc.declarations.append(self._parse_realization())
            elif self.at(TokenKind.АССОЦИАЦИЯ):
                doc.declarations.append(self._parse_association())
            elif self.at(TokenKind.КОМПОЗИЦИЯ):
                doc.declarations.append(self._parse_composition())
            elif self.at(TokenKind.АГРЕГАЦИЯ):
                doc.declarations.append(self._parse_aggregation())
            elif self.at(TokenKind.КЛАСС_АССОЦИАЦИИ):
                doc.declarations.append(self._parse_association_class())
            elif self.at(TokenKind.EOF):
                break
            else:
                raise ParseError(f"Неожиданное начало объявления: {self.peek().kind.name}", self.peek())
        return doc


def parse_tdl(tokens: List[Token]) -> Document:
    return Parser(tokens).parse()
