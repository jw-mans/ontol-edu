"""
Streamlit-приложение: валидация UML-диаграмм (SVG) и рендер TDL → SVG.
"""
import sys
from pathlib import Path

# Корень проекта (родитель папки uml_dsl)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from uml_dsl.svg_parser import parse_svg_to_diagram, ParseResult
from uml_dsl.diagram import ClassDiagram
from uml_dsl.export import svg_to_png, svg_to_jpg, export_available
from uml_dsl.graphviz_render import available_svg_themes
from uml_dsl.tdl_run import tdl_to_svg
from uml_dsl.tdl_lexer import lex, LexerError
from uml_dsl.tdl_parser import parse_tdl, ParseError
from uml_dsl.tdl_build import build_diagram


st.set_page_config(
    page_title="UML — Валидатор и TDL",
    page_icon="✅",
    layout="wide"
)

st.title("UML: Валидатор и рендер TDL")
tab_val, tab_tdl = st.tabs(["Валидатор SVG", "Рендер TDL"])


def svg_preview_html(svg_content: str) -> str:
    return f"""
    <style>
      html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
      }}
    </style>
    {svg_content}
    """

# ═══════════════════════════════════════════════════════════════════════════
# Вкладка: Рендер TDL
# ═══════════════════════════════════════════════════════════════════════════
with tab_tdl:
    st.subheader("TDL → SVG")
    st.markdown("Введите текст на TDL или загрузите файл `.tdl` — получите SVG-диаграмму.")

    example_tdl_path = PROJECT_ROOT / "examples" / "app" / "render_tdl" / "example.tdl"
    default_tdl = ""
    if example_tdl_path.exists():
        default_tdl = example_tdl_path.read_text(encoding="utf-8")

    col_tdl_left, col_tdl_right = st.columns([1, 1])
    with col_tdl_left:
        tdl_file = st.file_uploader("Загрузить .tdl", type=["tdl"], key="tdl_upload")
        if tdl_file:
            tdl_content = tdl_file.read().decode("utf-8")
        else:
            tdl_content = st.text_area(
                "Текст TDL",
                value=default_tdl,
                height=320,
                placeholder="КЛАСС Имя ... КОНЕЦ КЛАСС",
                key="tdl_text",
        )
        svg_themes = available_svg_themes()
        default_theme_idx = svg_themes.index("light") if "light" in svg_themes else 0
        svg_theme = st.selectbox(
            "Тема SVG",
            svg_themes,
            index=default_theme_idx,
            help="CSS-файл из uml_dsl/styles, который будет встроен в итоговый SVG.",
            key="tdl_svg_theme",
        )
        if st.button("Сгенерировать SVG", type="primary", key="tdl_render"):
            st.session_state["tdl_do_render"] = True

    with col_tdl_right:
        if st.session_state.get("tdl_do_render") and tdl_content.strip():
            st.session_state["tdl_do_render"] = False
            with st.spinner("Парсинг TDL и рендер..."):
                try:
                    svg_tdl = tdl_to_svg(tdl_content.strip(), theme=svg_theme)
                    st.session_state["current_svg"] = svg_tdl
                    st.success("Диаграмма построена")
                    st.components.v1.html(svg_preview_html(svg_tdl), height=400)
                    st.download_button(
                        "Скачать SVG",
                        data=svg_tdl,
                        mime="image/svg+xml",
                        file_name="diagram.svg",
                        key="dl_svg_tdl",
                    )
                    if export_available():
                        st.download_button("Скачать PNG", data=svg_to_png(svg_tdl), mime="image/png", file_name="diagram.png", key="dl_png_tdl")
                        st.download_button("Скачать JPG", data=svg_to_jpg(svg_tdl), mime="image/jpeg", file_name="diagram.jpg", key="dl_jpg_tdl")
                except LexerError as e:
                    st.error(f"Ошибка лексера: {e}")
                except ParseError as e:
                    st.error(f"Ошибка парсера: {e}")
                except ValueError as e:
                    st.error(f"Ошибка модели/валидации: {e}")
        else:
            st.info("Введите TDL и нажмите «Сгенерировать SVG»")

# ═══════════════════════════════════════════════════════════════════════════
# Вкладка: Валидатор SVG
# ═══════════════════════════════════════════════════════════════════════════
with tab_val:
    st.subheader("Валидатор UML-диаграмм")
    st.markdown("Загрузите SVG-файл с UML-диаграммой — проверим семантику (циклы наследования, композицию, конфликты)")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. Загрузите SVG")
        uploaded_file = st.file_uploader(
            "Выберите SVG-файл",
            type=['svg'],
            help="Файл должен содержать data-атрибуты (сгенерированные нашей системой)"
        )
        validate_button = st.button("Валидировать", type="primary", use_container_width=True)
        st.divider()
        st.subheader("Или используйте пример")
        col_ex1, col_ex2 = st.columns(2)
        with col_ex1:
            if st.button("📄 Пример 1 (корректный)", use_container_width=True):
                example_path = PROJECT_ROOT / "examples" / "app" / "validate_svg" / "imported_svg_01.svg"
                if example_path.exists():
                    with open(example_path, 'rb') as f:
                        uploaded_file = f.read()
                    st.session_state['uploaded_file'] = uploaded_file
                    st.session_state['run_validation'] = True
                else:
                    st.error("Файл примера не найден. Сначала запустите tests/scripts/generate_svg_parser_examples.py")
        with col_ex2:
            if st.button("📄 Пример 2 (метамодель)", use_container_width=True):
                example_path = PROJECT_ROOT / "examples" / "app" / "validate_svg" / "tdl_example.svg"
                if example_path.exists():
                    with open(example_path, 'rb') as f:
                        uploaded_file = f.read()
                    st.session_state['uploaded_file'] = uploaded_file
                    st.session_state['run_validation'] = True
                else:
                    st.error("Файл примера не найден")

    with col2:
        st.subheader("2. Результат валидации")
        result_container = st.container()
        with result_container:
            if validate_button or st.session_state.get('run_validation', False):
                if 'run_validation' in st.session_state:
                    del st.session_state['run_validation']
                if uploaded_file is not None:
                    if hasattr(uploaded_file, 'read'):
                        svg_content = uploaded_file.read().decode('utf-8')
                    else:
                        svg_content = uploaded_file.decode('utf-8') if isinstance(uploaded_file, bytes) else uploaded_file
                    st.session_state["current_svg"] = svg_content
                    with st.expander("📊 Превью SVG", expanded=False):
                        st.components.v1.html(svg_preview_html(svg_content), height=300)
                    with st.spinner("Парсинг и валидация..."):
                        try:
                            # Первый уровень: парсинг SVG
                            parse_result = parse_svg_to_diagram(svg_content)
                            
                            if not parse_result.success:
                                st.error("❌ Ошибка парсинга SVG:\n" + "\n".join(
                                    f"• {err}" for err in parse_result.errors
                                ))
                            else:
                                st.success("✅ SVG успешно распарсился (data-атрибуты корректны)")
                                
                                # Показываем предупреждения, если они есть
                                if parse_result.warnings:
                                    st.warning("⚠️ Предупреждения при парсинге:\n" + "\n".join(
                                        f"• {warn}" for warn in parse_result.warnings
                                    ))
                                
                                diagram = parse_result.diagram
                                
                                # Второй уровень: семантическая валидация
                                try:
                                    diagram.validate_all()
                                    st.success("✅ Диаграмма семантически корректна!")
                                    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                                    with col_stat1:
                                        st.metric("Классы", len(diagram.classifiers))
                                    with col_stat2:
                                        st.metric("Ассоциации", len(diagram.associations))
                                    with col_stat3:
                                        st.metric("Обобщения", len(diagram.generalizations))
                                    with col_stat4:
                                        st.metric("Зависимости", len(diagram.dependencies))
                                    with st.expander("📋 Детали модели"):
                                        st.json({
                                            "title": diagram.title,
                                            "classifiers": list(diagram.classifiers.keys()),
                                            "associations_count": len(diagram.associations),
                                            "generalizations_count": len(diagram.generalizations),
                                            "dependencies_count": len(diagram.dependencies),
                                            "realizations_count": len(diagram.realizations),
                                        })
                                except ValueError as e:
                                    st.error(f"❌ Семантическая ошибка: {e}")
                                    st.info("Модель распарсена, но не прошла валидацию:")
                                    st.write(f"- Классов: {len(diagram.classifiers)}")
                                    st.write(f"- Отношений: {len(diagram.associations) + len(diagram.generalizations) + len(diagram.dependencies)}")
                        except Exception as e:
                            st.error(f"❌ Критическая ошибка: {e}")
                            st.exception(e)
                else:
                    st.info("👈 Загрузите SVG-файл для валидации")

# Боковая панель с информацией
with st.sidebar:
    st.header("ℹ️ О проекте")
    st.markdown("""
    **Валидатор SVG** — проверка семантики UML-диаграмм (циклы, композиция, конфликты).
    
    **Рендер TDL** — введите или загрузите текст на TDL → получите SVG-диаграмму и экспорт в PNG/JPG.
    
    **Что проверяем (SVG):**
    - 🔄 Циклы наследования
    - 🧩 Композиция
    - ⚔️ Конфликты множественного наследования
    - 🔗 Ссылки на несуществующие классы
    - 📏 Корректность кратности
    
    **Формат SVG:** data-атрибуты (`data-type="class"`, `data-src`, `data-tgt` и т.д.)
    """)
    
    st.divider()
    st.subheader("Экспорт в растр")
    if export_available():
        current_svg = st.session_state.get("current_svg")
        if current_svg:
            png_bytes = svg_to_png(current_svg)
            jpg_bytes = svg_to_jpg(current_svg)
            st.download_button(
                "📥 Скачать PNG",
                data=png_bytes,
                mime="image/png",
                file_name="diagram.png",
                use_container_width=True,
            )
            st.download_button(
                "📥 Скачать JPG",
                data=jpg_bytes,
                mime="image/jpeg",
                file_name="diagram.jpg",
                use_container_width=True,
            )
        else:
            st.caption("Загрузите SVG для экспорта")
    else:
        st.caption("Установите cairosvg и Pillow для экспорта PNG/JPG")

    st.divider()
    if st.button("🔄 Сгенерировать примеры", use_container_width=True):
        with st.spinner("Генерация..."):
            try:
                sys.path.insert(0, str(PROJECT_ROOT / "tests" / "scripts"))
                import generate_svg_parser_examples
                generate_svg_parser_examples.main()
                st.success("Примеры сгенерированы в tests/fixtures/svg_parser/")
            except Exception as e:
                st.error(f"Ошибка: {e}")
