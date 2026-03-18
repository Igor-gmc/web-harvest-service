"""Селекторы для fedresurs.ru и kad.arbitr.ru.

Селекторы на реальных сайтах часто меняются, поэтому для каждого элемента
хранится список кандидатов — от самого надёжного к менее надёжному.
"""

# Логотип (для возврата на главную)
FEDRESURS_LOGO_CANDIDATES: list[str] = [
    'span.logo.logo__img-wrapper',
    '.logo__img-wrapper',
    'a.logo',
]

# Поле ввода ИНН / наименования
FEDRESURS_SEARCH_INPUT_CANDIDATES: list[str] = [
    'input[formcontrolname="searchString"]',
    'd-el-search-input input[type="text"]',
    '.el-search-input-field input',
    'input[maxlength="300"]',
]

# Кнопка "Найти" (лупа)
FEDRESURS_SEARCH_BUTTON_CANDIDATES: list[str] = [
    'el-button.form__btn.inside-input button',
    'el-button.inside-input button.el-button',
    '.form__btn button.el-button',
    'button.el-button',
]

# --- Страница результатов поиска ---

# Одна карточка результата (юр. лицо)
FEDRESURS_RESULT_CARD_CANDIDATES: list[str] = [
    'app-entity-search-result-card-company',
    '.u-card-result',
    'app-entity-search-result-companies',
]

# Кнопка/ссылка "Вся информация" (переход в карточку лица)
FEDRESURS_ENTITY_LINK_CANDIDATES: list[str] = [
    'el-info-link a.info.info_position',
    'a.info.info_position',
    'el-info-link a',
    'a.info_position',
]

# Кнопка поиска (лупа) на странице результатов — для повторного поиска
FEDRESURS_RESULTS_SEARCH_BUTTON_CANDIDATES: list[str] = [
    'div.itm-lupa',
    '.itm-lupa',
]

# Маркер "Ничего не найдено" — ТОЛЬКО в активной вкладке
FEDRESURS_NO_RESULTS_CANDIDATES: list[str] = [
    'el-tab.selected .no-result-msg',
    '.tab-content el-tab:first-child .no-result-msg',
    '.no-result-msg-header',
]

# Панель вкладок (признак загрузки страницы результатов)
FEDRESURS_TAB_PANEL_CANDIDATES: list[str] = [
    'el-tab-panel .tab__nav',
    '.tab__btn_active',
    'el-tab-panel',
    'app-entity-search-result',
]

# --- Карточка лица (все секции на одной странице) ---

# Блок банкротства (секция на странице карточки)
FEDRESURS_BANKRUPTCY_BLOCK_CANDIDATES: list[str] = [
    '.bankruptcy-block',
    'entity-card-bankruptcy',
    'company-card-bankruptcy',
    'information-page-item[selector="bankrupt"]',
]

# Номер дела (ссылка внутри блока банкротства)
FEDRESURS_CASE_NUMBER_CANDIDATES: list[str] = [
    '.bankruptcy-block .legalcase-item a.underlined.info-header',
    '.bankruptcy-block a.info-header[href*="legalcases"]',
    '.legalcase-item a.info-header',
    'a.info-header[href*="legalcases"]',
]

# Публикации по банкротству (для извлечения дат)
FEDRESURS_PUBLICATIONS_CANDIDATES: list[str] = [
    '.bankruptcy-block entity-card-bankruptcy-publication-wrapper.pub-item a.underlined[href*="bankruptmessages"]',
    '.bankruptcy-block entity-card-bankruptcy-publication-wrapper.pub-item',
    'entity-card-bankruptcy-publication-wrapper.pub-item',
]


# =====================================================================
# kad.arbitr.ru
# =====================================================================

KAD_URL = "https://kad.arbitr.ru/"

# Поле ввода номера дела (placeholder "например, А50-5568/08")
KAD_SEARCH_INPUT_CANDIDATES: list[str] = [
    '#sug-cases input.g-ph',
    '#sug-cases input[type="text"]',
    '.b-selected-tags#sug-cases input',
    '#sug-cases input',
]

# --- Реакция на поиск ---

# Таблица с результатами
KAD_RESULTS_TABLE_CANDIDATES: list[str] = [
    '#b-cases',
    '.b-results table.b-cases',
    '.b-results .b-cases_wrapper table',
]

# Ссылка на дело внутри таблицы результатов
KAD_CASE_LINK_CANDIDATES: list[str] = [
    '#b-cases a.num_case',
    '.b-cases a.num_case',
    'td.num a.num_case',
]

# "Нет результатов"
KAD_NO_RESULTS_CANDIDATES: list[str] = [
    '.b-noResults:not(.g-hidden)',
    '.b-noResults h2',
]

# Индикатор загрузки
KAD_LOADING_CANDIDATES: list[str] = [
    '.b-case-loading:not([style*="display: none"])',
]

# Логотип "Электронное правосудие" (возврат на главную)
KAD_LOGO_CANDIDATES: list[str] = [
    '.b-arbitr-header-title a[href="/"]',
    'td.b-arbitr-header-title a[href="/"]',
    'h1 + a[href="/"]',
]

# --- Карточка дела ---

# Хронология дела на странице карточки
KAD_CHRONO_TABLE_CANDIDATES: list[str] = [
    '.b-case-chrono',
    '#main-column .b-case-chrono',
    '.b-case-card-content .b-case-chrono',
]

# Дата внутри хронологии
KAD_CHRONO_DATE_SELECTOR = 'span.b-reg-date'

# Документ (название + ссылка на PDF)
KAD_CHRONO_DOCUMENT_CANDIDATES: list[str] = [
    'h2.b-case-result a[href*="PdfDocument"]',
    'h2.b-case-result a',
    '.b-case-result a',
]
