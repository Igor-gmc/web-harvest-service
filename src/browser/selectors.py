"""Селекторы для fedresurs.ru.

Селекторы на реальных сайтах часто меняются, поэтому для каждого элемента
хранится список кандидатов — от самого надёжного к менее надёжному.
"""

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
