import asyncio
import logging
logging.basicConfig(level=logging.DEBUG)
import sys
import os
import signal
import re
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, FSInputFile, InputMedia, PhotoSize, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from database import Database

# Конфигурация
TOKEN = '8592177753:AAEJ1oSANrgApnVY-6dP27PEkf5Y4HBrEW4'
MANAGER_USERNAME = '@AsiaHappyManager'

# Админы (только эти пользователи имеют доступ к админке)
ADMINS = ['seamlx', 'Adecvat22']

# Инициализация базы данных
db = Database()

# Инициализация FSM storage
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Хранилище состояний пользователей
class UserState:
    def __init__(self):
        self.category: Optional[str] = None
        self.type: Optional[str] = None
        self.subcategory: Optional[str] = None
        self.current_product: Optional[int] = None
        self.product_photos: List[str] = []
        self.current_photo_index: int = 0
        # Добавляем новые поля
        self.current_product_page: int = 0
        self.all_products_list: List[Dict] = []

user_states: Dict[int, UserState] = {}

# Состояния для админки
class AdminStates(StatesGroup):
    # Добавление категории
    waiting_for_category_name = State()
    waiting_for_category_slug = State()
    
    # Редактирование категории
    waiting_for_edit_category = State()
    waiting_for_new_category_name = State()
    waiting_for_new_category_slug = State()
    
    # Удаление категории
    waiting_for_delete_category = State()
    
    # Добавление подкатегории
    waiting_for_subcategory_category = State()
    waiting_for_subcategory_type = State()
    waiting_for_subcategory_name = State()
    waiting_for_subcategory_slug = State()
    
    # Редактирование подкатегории
    waiting_for_edit_subcategory = State()
    waiting_for_edit_subcategory_field = State()
    waiting_for_edit_subcategory_value = State()
    
    # Удаление подкатегории
    waiting_for_delete_subcategory = State()
    
    # Добавление товара
    waiting_for_product_category = State()
    waiting_for_product_type = State()
    waiting_for_product_subcategory = State()
    waiting_for_product_name = State()
    waiting_for_product_price = State()
    waiting_for_product_description = State()
    waiting_for_product_photos = State()
    waiting_for_product_tags = State()
    
    # Редактирование товара
    waiting_for_edit_product = State()
    waiting_for_edit_product_field = State()
    waiting_for_edit_product_value = State()
    
    # Удаление товара
    waiting_for_delete_product = State()

    # Редактирование фотографий товара
    waiting_for_edit_product_photos_menu = State()  # Меню управления фото
    waiting_for_add_product_photos = State()         # Добавление новых фото
    waiting_for_delete_product_photo = State()       # Удаление фото
    waiting_for_replace_product_photo = State()      # Замена фото
    
    # Бан пользователя
    waiting_for_username_to_ban = State()
    
    # Разбан пользователя
    waiting_for_username_to_unban = State()
    
    # Поиск товаров
    waiting_for_search_query = State()

     # Рассылка сообщений
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_confirmation = State()

def get_user_state(user_id: int) -> UserState:
    """Получить или создать состояние пользователя"""
    if user_id not in user_states:
        user_states[user_id] = UserState()
    return user_states[user_id]

def check_photo_file(photo_path: str) -> bool:
    """Проверка существования файла с фото"""
    if not photo_path:
        return False
    
    # Проверяем разные варианты пути
    paths_to_check = [
        photo_path,
        f"./{photo_path}",
        photo_path.lstrip('/'),
        f"img/{photo_path}" if not photo_path.startswith('img/') else None,
        photo_path if photo_path.startswith('img/') else f"img/{photo_path}"
    ]
    
    for path in paths_to_check:
        if path and os.path.exists(path):
            return True
    
    return False

def get_available_photos(photo_urls: List[str]) -> List[str]:
    """Получить список доступных фото"""
    available = []
    for photo in photo_urls:
        if check_photo_file(photo):
            available.append(photo)
    return available

async def is_admin(user_id: int, username: Optional[str]) -> bool:
    """Проверка, является ли пользователь админом"""
    if not username:
        return False
    
    # Убираем @ если есть
    if username.startswith('@'):
        username = username[1:]
    
    return username in ADMINS

async def delete_previous_message(callback: CallbackQuery):
    """Удалить предыдущее сообщение бота"""
    try:
        await callback.message.delete()
    except Exception:
        pass  # Игнорируем ошибки удаления

async def send_product_with_photos(
    callback: CallbackQuery, 
    product: Dict, 
    photo_urls: List[str],
    current_index: int = 0
) -> None:
    """
    Отправка товара с фото и кнопками навигации
    """
    user_id = callback.from_user.id
    user_state = get_user_state(user_id)
    
    # Сохраняем информацию о фото
    user_state.product_photos = photo_urls
    user_state.current_photo_index = current_index
    user_state.current_product = None
    
    # Формируем кнопки
    builder = InlineKeyboardBuilder()
    
    # Кнопки навигации по фото
    if len(photo_urls) > 1:
        # Кнопка "Предыдущее фото" если не первое
        if current_index > 0:
            builder.button(text="⬅️ Предыдущее", callback_data=f"prev_{current_index}")
        
        # Кнопка "Следующее фото" если не последнее
        if current_index < len(photo_urls) - 1:
            builder.button(text="Следующее ➡️", callback_data=f"next_{current_index}")
    
    # Основные кнопки
    builder.button(text="✍️ Написать продавцу", url=f"https://t.me/{MANAGER_USERNAME.lstrip('@')}")
    
    # Кнопка "Назад"
    if user_state.category and user_state.type and user_state.subcategory:
        builder.button(text="⬅️ Назад к товарам", callback_data=f"back_to_list")
    
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    
    # Кнопка поиска (только для пользователей)
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    
    # Располагаем кнопки
    if len(photo_urls) > 1:
        builder.adjust(2, 1, 1, 1)
    else:
        builder.adjust(1, 1, 1)
    
    # Формируем описание
    caption = (
        f"<b>🏷️ {product['name']}</b>\n"
        f"<b>💰 Цена:</b> {product['price']}\n"
        f"<b>📦 Тип:</b> {'📅 Предзаказ' if product.get('type') == 'preorder' else '✅ В наличии'}\n\n"
        f"<b>📝 Описание:</b>\n{product['description']}\n\n"
    )
    
    # Добавляем информацию о количестве фото
    if len(photo_urls) > 1:
        caption += f"📸 <i>Всего фото: {len(photo_urls)}</i>\n\n"
    
    caption += "Для заказа нажмите кнопку ниже:"
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    # Отправляем фото
    try:
        if photo_urls and current_index < len(photo_urls):
            photo_path = photo_urls[current_index]
            
            # Находим правильный путь
            actual_path = None
            if os.path.exists(photo_path):
                actual_path = photo_path
            elif os.path.exists(f"./{photo_path}"):
                actual_path = f"./{photo_path}"
            elif photo_path.startswith('img/') and os.path.exists(photo_path):
                actual_path = photo_path
            elif photo_path.startswith('img/') and os.path.exists(f"./{photo_path}"):
                actual_path = f"./{photo_path}"
            elif os.path.exists(f"img/{photo_path}"):
                actual_path = f"img/{photo_path}"
            
            if actual_path and os.path.exists(actual_path):
                photo = FSInputFile(actual_path)
                
                # Регистрируем клик по товару
                db.increment_product_clicks(user_id, product.get('id', 0))
                
                await callback.message.answer_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
            else:
                await send_product_as_text(callback, product, builder)
        else:
            await send_product_as_text(callback, product, builder)
            
    except Exception:
        await send_product_as_text(callback, product, builder)

async def send_product_as_text(
    callback: CallbackQuery, 
    product: Dict, 
    builder: InlineKeyboardBuilder
) -> None:
    """Отправка товара в виде текста"""
    text_message = (
        f"<b>🏷️ {product['name']}</b>\n"
        f"<b>💰 Цена:</b> {product['price']}\n"
        f"<b>📦 Тип:</b> {'📅 Предзаказ' if product.get('type') == 'preorder' else '✅ В наличии'}\n\n"
        f"<b>📝 Описание:</b>\n{product['description']}\n\n"
        f"📸 <i>Фото товара временно недоступно</i>\n\n"
        "Для заказа нажмите кнопку ниже:"
    )
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    await callback.message.answer(
        text_message,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """Обработчик команды /start"""
    # Регистрируем пользователя
    db.register_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    # Обновляем активность
    db.update_user_activity(message.from_user.id)
    
    # Проверяем бан
    if db.is_user_banned(message.from_user.id):
        await message.answer(
            "🚫 <b>Доступ запрещен</b>\n\n"
            "Вы были заблокированы администратором.",
            parse_mode=ParseMode.HTML
        )
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer(
            "🌟 <b>Рады приветствовать тебя в боте «AsiaHappy»</b> 🌟\n\n"
            "Каталог товаров временно недоступен.\n"
            "Пожалуйста, попробуйте позже.",
            parse_mode=ParseMode.HTML
        )
        return
    
    builder = InlineKeyboardBuilder()
    
    for slug, name in categories.items():
        builder.button(text=name, callback_data=f"category_{slug}")
    
    # Добавляем кнопку "Все товары"
    builder.button(text="📦 Все товары", callback_data="all_products")
    
    # Добавляем кнопки помощи и поиска
    builder.button(text="🆘 Помощь / Справка", callback_data="show_help")
    builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    
    builder.adjust(1)
    
    await message.answer(
        "🌟 <b>Рады приветствовать тебя в боте «AsiaHappy»</b> 🌟\n\n"
        "<i>Магазин коллекционных товаров: Funko Pop, конструкторы Lego и аналоги</i>\n\n"
        "👨‍💼 <b>Менеджер:</b> @AsiaHappyManager\n\n"
        "Доступные команды:\n"
        "• /help - Помощь и справка\n"
        "• /catalog - Открыть каталог\n"
        "• /allproducts - Все товары\n\n"
        "Выберите категорию товаров или посмотрите все товары:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'show_help')
async def show_help_handler(callback: CallbackQuery):
    """Показать справку"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    help_text = (
        "🆘 <b>Помощь по боту AsiaHappy</b>\n\n"
        
        "<b>📋 Основные команды:</b>\n"
        "• /start - Запустить бота\n"
        "• /catalog - Открыть каталог\n"
        "• /help - Эта справка\n\n"
        
        "<b>💡 Как пользоваться:</b>\n"
        "1. Выберите категорию товаров\n"
        "2. Выберите тип (В наличии/Предзаказ)\n"
        "3. Выберите подкатегорию (если есть)\n"
        "4. Выберите товар из списка\n"
        "5. Листайте фото с помощью кнопок\n"
        "6. Для заказа нажмите 'Написать продавцу'\n\n"
        
        "<b>🔍 Поиск товаров:</b>\n"
        "• Используйте кнопку 'Поиск товаров' для поиска по ключевым словам\n"
        "• Или команду /catalog для просмотра всего каталога\n\n"
        
        "<b>📞 Контакты:</b>\n"
        "👨‍💼 Менеджер: @AsiaHappyManager\n\n"
        
        "<i>Каталог обновляется регулярно!</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    builder.adjust(1)
    
    await callback.message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.message(Command('help'))
async def help_command(message: Message):
    """Команда /help"""
    # Обновляем активность
    db.update_user_activity(message.from_user.id)
    
    help_text = (
        "🆘 <b>Помощь по боту AsiaHappy</b>\n\n"
        
        "<b>📋 Основные команды:</b>\n"
        "• /start - Запустить бота\n"
        "• /catalog - Открыть каталог\n"
        "• /help - Эта справка\n\n"
        
        "<b>💡 Как пользоваться:</b>\n"
        "1. Выберите категорию товаров\n"
        "2. Выберите тип (В наличии/Предзаказ)\n"
        "3. Выберите подкатегорию (если есть)\n"
        "4. Выберите товар из списка\n"
        "5. Листайте фото с помощью кнопок\n"
        "6. Для заказа нажмите 'Написать продавцу'\n\n"
        
        "<b>🔍 Поиск товаров:</b>\n"
        "• Используйте кнопку 'Поиск товаров' для поиска по ключевым словам\n"
        "• Или команду /catalog для просмотра всего каталога\n\n"
        
        "<b>📞 Контакты:</b>\n"
        "👨‍💼 Менеджер: @AsiaHappyManager\n\n"
        
        "<i>Каталог обновляется регулярно!</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    builder.adjust(1)
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('category_'))
async def process_category(callback: CallbackQuery):
    """Обработчик выбора категории"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    category_slug = callback.data.split('_')[1]
    categories = db.get_categories()
    category_name = categories.get(category_slug, "Категория")
    
    if not category_name:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    # Сохраняем выбор пользователя
    user_state = get_user_state(callback.from_user.id)
    user_state.category = category_slug
    user_state.type = None
    user_state.subcategory = None
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ В наличии", callback_data=f"type_{category_slug}_instock")
    builder.button(text="📅 Предзаказ", callback_data=f"type_{category_slug}_preorder")
    builder.button(text="⬅️ Назад", callback_data="back_to_main")
    builder.adjust(1)
    
    await callback.message.answer(
        f"<b>{category_name}</b>\n\n"
        "Выберите тип товаров:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('type_'))
async def process_type(callback: CallbackQuery):
    """Обработчик выбора типа товаров"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    try:
        _, category_slug, type_ = callback.data.split('_')
        categories = db.get_categories()
        category_name = categories.get(category_slug, "Категория")
        
        if not category_name:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        
        # Сохраняем выбор типа
        user_state = get_user_state(callback.from_user.id)
        user_state.category = category_slug
        user_state.type = type_
        user_state.subcategory = None
        
        # Получаем подкатегории для выбранной категории и типа
        subcategories = db.get_subcategories_by_category_and_type(category_slug, type_)
        
        if not subcategories:
            # Если нет подкатегорий, показываем все товары сразу
            products = db.get_products_by_category_and_type(category_slug, type_)
            
            if not products:
                type_display = "в наличии" if type_ == 'instock' else "предзаказ"
                type_icon = "✅" if type_ == 'instock' else "📅"
                
                # Для другой категории предлагаем посмотреть другой тип
                other_type = 'preorder' if type_ == 'instock' else 'instock'
                other_type_display = "предзаказ" if other_type == 'preorder' else "в наличии"
                other_type_icon = "📅" if other_type == 'preorder' else "✅"
                
                builder = InlineKeyboardBuilder()
                builder.button(text=f"{other_type_icon} Посмотреть {other_type_display}", callback_data=f"type_{category_slug}_{other_type}")
                builder.button(text="⬅️ Назад", callback_data=f"category_{category_slug}")
                builder.adjust(1)
                
                await callback.message.answer(
                    f"<b>{category_name}</b>\n\n"
                    f"{type_icon} <b>В данной категории нет товаров {type_display}.</b>\n\n"
                    f"Но вы можете посмотреть товары в {other_type_display} 👇",
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
                return
            
            # Показываем товары напрямую
            type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
            
            builder = InlineKeyboardBuilder()
            
            for product in products:
                # Обрезаем длинные названия
                product_name = product['name']
                if len(product_name) > 35:
                    product_name = product_name[:32] + "..."
                
                builder.button(
                    text=f"{product_name} - {product['price']}",
                    callback_data=f"product_{product['id']}"
                )
            
            builder.button(text="⬅️ Назад", callback_data=f"category_{category_slug}")
            builder.adjust(1)
            
            await callback.message.answer(
                f"<b>{category_name}</b> - {type_names[type_]}\n\n"
                f"Найдено товаров: {len(products)}\n"
                "Выберите товар для просмотра:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        else:
            # Показываем подкатегории
            type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
            
            builder = InlineKeyboardBuilder()
            
            for subcat in subcategories:
                builder.button(text=subcat['name'], callback_data=f"subcategory_{category_slug}_{type_}_{subcat['slug']}")
            
            builder.button(text="⬅️ Назад", callback_data=f"category_{category_slug}")
            builder.adjust(1)
            
            await callback.message.answer(
                f"<b>{category_name}</b> - {type_names[type_]}\n\n"
                "Выберите подкатегорию:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        
    except Exception as e:
        print(f"Error in process_type: {e}")
        await callback.answer("Ошибка при загрузке товаров", show_alert=True)

@dp.callback_query(F.data.startswith('subcategory_'))
async def process_subcategory(callback: CallbackQuery):
    """Обработчик выбора подкатегории"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    try:
        _, category_slug, type_, subcategory_slug = callback.data.split('_')
        categories = db.get_categories()
        category_name = categories.get(category_slug, "Категория")
        
        # Получаем информацию о подкатегории
        subcategories = db.get_subcategories_by_category_and_type(category_slug, type_)
        subcategory_name = None
        for subcat in subcategories:
            if subcat['slug'] == subcategory_slug:
                subcategory_name = subcat['name']
                break
        
        if not category_name or not subcategory_name:
            await callback.answer("Подкатегория не найдена", show_alert=True)
            return
        
        # Сохраняем выбор подкатегории
        user_state = get_user_state(callback.from_user.id)
        user_state.category = category_slug
        user_state.type = type_
        user_state.subcategory = subcategory_slug
        
        # Получаем товары из базы данных
        products = db.get_products_by_category_and_type(category_slug, type_, subcategory_slug)
        
        if not products:
            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Назад", callback_data=f"type_{category_slug}_{type_}")
            builder.adjust(1)
            
            type_display = "предзаказ" if type_ == 'preorder' else "наличии"
            type_icon = "📅" if type_ == 'preorder' else "✅"
            
            await callback.message.answer(
                f"<b>{category_name} - {subcategory_name}</b>\n\n"
                f"{type_icon} <b>В данной подкатегории нет товаров в {type_display}.</b>\n\n"
                "Выберите другую подкатегорию:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
        
        builder = InlineKeyboardBuilder()
        
        for product in products:
            # Обрезаем длинные названия
            product_name = product['name']
            if len(product_name) > 35:
                product_name = product_name[:32] + "..."
            
            builder.button(
                text=f"{product_name} - {product['price']}",
                callback_data=f"product_{product['id']}"
            )
        
        builder.button(text="⬅️ Назад", callback_data=f"type_{category_slug}_{type_}")
        builder.adjust(1)
        
        await callback.message.answer(
            f"<b>{category_name} - {subcategory_name}</b> - {type_names[type_]}\n\n"
            f"Найдено товаров: {len(products)}\n"
            "Выберите товар для просмотра:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Error in process_subcategory: {e}")
        await callback.answer("Ошибка при загрузке товаров", show_alert=True)

@dp.callback_query(F.data.startswith('product_'))
async def show_product(callback: CallbackQuery):
    """Показать товар с фото"""
    try:
        # Проверяем бан
        if db.is_user_banned(callback.from_user.id):
            await callback.answer("Доступ запрещен", show_alert=True)
            return
        
        # Обновляем активность
        db.update_user_activity(callback.from_user.id)
        
        product_id = int(callback.data.split('_')[1])
        
        # Получаем товар из базы данных
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        # Получаем все доступные фото
        photo_urls = product.get('photo_urls', [])
        available_photos = get_available_photos(photo_urls)
        
        # Отправляем товар с первым фото
        await send_product_with_photos(callback, product, available_photos, 0)
        
    except Exception as e:
        print(f"Error in show_product: {e}")
        await callback.answer("Ошибка при загрузке товара", show_alert=True)

@dp.callback_query(F.data.startswith('next_'))
async def next_photo_handler(callback: CallbackQuery):
    """Следующее фото"""
    try:
        # Проверяем бан
        if db.is_user_banned(callback.from_user.id):
            await callback.answer("Доступ запрещен", show_alert=True)
            return
        
        # Обновляем активность
        db.update_user_activity(callback.from_user.id)
        
        current_index = int(callback.data.split('_')[1])
        user_state = get_user_state(callback.from_user.id)
        
        if not user_state.product_photos:
            await callback.answer("Нет доступных фото", show_alert=True)
            return
        
        # Получаем следующий индекс
        next_index = current_index + 1
        
        if next_index >= len(user_state.product_photos):
            await callback.answer("Это последнее фото", show_alert=True)
            return
        
        # Получаем информацию о товаре из последнего сообщения
        caption = callback.message.caption or ""
        
        # Создаем новый builder
        builder = InlineKeyboardBuilder()
        
        if len(user_state.product_photos) > 1:
            if next_index > 0:
                builder.button(text="⬅️ Предыдущее", callback_data=f"prev_{next_index}")
            
            if next_index < len(user_state.product_photos) - 1:
                builder.button(text="Следующее ➡️", callback_data=f"next_{next_index}")
        
        builder.button(text="✍️ Написать продавцу", url=f"https://t.me/{MANAGER_USERNAME.lstrip('@')}")
        
        if user_state.category and user_state.type and user_state.subcategory:
            builder.button(text="⬅️ Назад к товарам", callback_data=f"back_to_list")
        
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        
        # Кнопка поиска для пользователей
        if not await is_admin(callback.from_user.id, callback.from_user.username):
            builder.button(text="🔍 Поиск товаров", callback_data="search_products")
        
        if len(user_state.product_photos) > 1:
            builder.adjust(2, 1, 1, 1)
        else:
            builder.adjust(1, 1, 1)
        
        # Обновляем информацию о количестве фото в описании
        if "📸 <i>Всего фото:" in caption:
            import re
            caption = re.sub(r"📸 <i>Всего фото: \d+</i>", f"📸 <i>Всего фото: {len(user_state.product_photos)}</i>", caption)
        
        # Отправляем следующее фото
        photo_path = user_state.product_photos[next_index]
        
        # Находим правильный путь
        actual_path = None
        if os.path.exists(photo_path):
            actual_path = photo_path
        elif os.path.exists(f"./{photo_path}"):
            actual_path = f"./{photo_path}"
        elif photo_path.startswith('img/') and os.path.exists(photo_path):
            actual_path = photo_path
        elif photo_path.startswith('img/') and os.path.exists(f"./{photo_path}"):
            actual_path = f"./{photo_path}"
        elif os.path.exists(f"img/{photo_path}"):
            actual_path = f"img/{photo_path}"
        
        if actual_path and os.path.exists(actual_path):
            photo = FSInputFile(actual_path)
            
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except TelegramBadRequest:
                await callback.message.answer_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
        
        # Обновляем состояние
        user_state.current_photo_index = next_index
        
    except Exception as e:
        print(f"Error in next_photo_handler: {e}")
        await callback.answer("Ошибка при переключении фото", show_alert=True)

@dp.callback_query(F.data.startswith('prev_'))
async def prev_photo_handler(callback: CallbackQuery):
    """Предыдущее фото"""
    try:
        # Проверяем бан
        if db.is_user_banned(callback.from_user.id):
            await callback.answer("Доступ запрещен", show_alert=True)
            return
        
        # Обновляем активность
        db.update_user_activity(callback.from_user.id)
        
        current_index = int(callback.data.split('_')[1])
        user_state = get_user_state(callback.from_user.id)
        
        if not user_state.product_photos:
            await callback.answer("Нет доступных фото", show_alert=True)
            return
        
        # Получаем предыдущий индекс
        prev_index = current_index - 1
        
        if prev_index < 0:
            await callback.answer("Это первое фото", show_alert=True)
            return
        
        caption = callback.message.caption or ""
        
        builder = InlineKeyboardBuilder()
        
        if len(user_state.product_photos) > 1:
            if prev_index > 0:
                builder.button(text="⬅️ Предыдущее", callback_data=f"prev_{prev_index}")
            
            if prev_index < len(user_state.product_photos) - 1:
                builder.button(text="Следущее ➡️", callback_data=f"next_{prev_index}")
        
        builder.button(text="✍️ Написать продавцу", url=f"https://t.me/{MANAGER_USERNAME.lstrip('@')}")
        
        if user_state.category and user_state.type and user_state.subcategory:
            builder.button(text="⬅️ Назад к товарам", callback_data=f"back_to_list")
        
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        
        # Кнопка поиска для пользователей
        if not await is_admin(callback.from_user.id, callback.from_user.username):
            builder.button(text="🔍 Поиск товаров", callback_data="search_products")
        
        if len(user_state.product_photos) > 1:
            builder.adjust(2, 1, 1, 1)
        else:
            builder.adjust(1, 1, 1)
        
        if "📸 <i>Всего фото:" in caption:
            import re
            caption = re.sub(r"📸 <i>Всего фото: \d+</i>", f"📸 <i>Всего фото: {len(user_state.product_photos)}</i>", caption)
        
        photo_path = user_state.product_photos[prev_index]
        
        actual_path = None
        if os.path.exists(photo_path):
            actual_path = photo_path
        elif os.path.exists(f"./{photo_path}"):
            actual_path = f"./{photo_path}"
        elif photo_path.startswith('img/') and os.path.exists(photo_path):
            actual_path = photo_path
        elif photo_path.startswith('img/') and os.path.exists(f"./{photo_path}"):
            actual_path = f"./{photo_path}"
        elif os.path.exists(f"img/{photo_path}"):
            actual_path = f"img/{photo_path}"
        
        if actual_path and os.path.exists(actual_path):
            photo = FSInputFile(actual_path)
            
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except TelegramBadRequest:
                await callback.message.answer_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
        
        user_state.current_photo_index = prev_index
        
    except Exception as e:
        print(f"Error in prev_photo_handler: {e}")
        await callback.answer("Ошибка при переключении фото", show_alert=True)

@dp.callback_query(F.data == 'back_to_list')
async def back_to_list_handler(callback: CallbackQuery):
    """Вернуться к списку товаров"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    user_state = get_user_state(callback.from_user.id)
    
    if user_state.category and user_state.type and user_state.subcategory:
        try:
            categories = db.get_categories()
            category_name = categories.get(user_state.category, "Категория")
            
            # Получаем информацию о подкатегории
            subcategories = db.get_subcategories_by_category_and_type(user_state.category, user_state.type)
            subcategory_name = None
            for subcat in subcategories:
                if subcat['slug'] == user_state.subcategory:
                    subcategory_name = subcat['name']
                    break
            
            if not subcategory_name:
                await back_to_main_handler(callback)
                return
            
            # Получаем товары из базы данных
            products = db.get_products_by_category_and_type(user_state.category, user_state.type, user_state.subcategory)
            
            if not products:
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data=f"type_{user_state.category}_{user_state.type}")
                builder.adjust(1)
                
                type_display = "предзаказ" if user_state.type == 'preorder' else "наличии"
                type_icon = "📅" if user_state.type == 'preorder' else "✅"
                
                await callback.message.answer(
                    f"<b>{category_name} - {subcategory_name}</b>\n\n"
                    f"{type_icon} <b>В данной подкатегории нет товаров в {type_display}.</b>\n\n"
                    "Выберите другую подкатегорию:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
                return
            
            type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
            
            builder = InlineKeyboardBuilder()
            
            for product in products:
                product_name = product['name']
                if len(product_name) > 35:
                    product_name = product_name[:32] + "..."
                
                builder.button(
                    text=f"{product_name} - {product['price']}",
                    callback_data=f"product_{product['id']}"
                )
            
            builder.button(text="⬅️ Назад", callback_data=f"type_{user_state.category}_{user_state.type}")
            builder.adjust(1)
            
            await callback.message.answer(
                f"<b>{category_name} - {subcategory_name}</b> - {type_names[user_state.type]}\n\n"
                f"Найдено товаров: {len(products)}\n"
                "Выберите товар для просмотра:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            print(f"Error in back_to_list_handler: {e}")
            await callback.answer("Ошибка при загрузке товаров", show_alert=True)
    elif user_state.category and user_state.type:
        # Если нет подкатегории, возвращаемся к выбору типа
        await process_type(callback)
    else:
        await back_to_main_handler(callback)

@dp.callback_query(F.data == 'back_to_main')
async def back_to_main_handler(callback: CallbackQuery):
    """Вернуться в главное меню"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    try:
        categories = db.get_categories()
        
        if not categories:
            await callback.answer("Каталог товаров временно недоступен", show_alert=True)
            return
        
        builder = InlineKeyboardBuilder()
        
        for slug, name in categories.items():
            builder.button(text=name, callback_data=f"category_{slug}")
        
        # Добавляем кнопку "Все товары"
        builder.button(text="📦 Все товары", callback_data="all_products")
        
        # Добавляем кнопки помощи и поиска
        builder.button(text="🆘 Помощь / Справка", callback_data="show_help")
        builder.button(text="🔍 Поиск товаров", callback_data="search_products")
        
        builder.adjust(1)
        
        await callback.message.answer(
            "🌟 <b>Рады приветствовать тебя в боте «AsiaHappy»</b> 🌟\n\n"
            "<i>Магазин коллекционных товаров: Funko Pop, конструкторы Lego и аналоги</i>\n\n"
            "👨‍💼 <b>Менеджер:</b> @AsiaHappyManager\n\n"
            "Доступные команды:\n"
            "• /help - Помощь и справка\n"
            "• /catalog - Открыть каталог\n"
            "• /allproducts - Все товары\n\n"
            "Выберите категорию товаров или посмотрите все товары:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        print(f"Error in back_to_main_handler: {e}")
        await callback.answer("Ошибка при загрузке главного меню", show_alert=True)

@dp.callback_query(F.data == 'all_products')
async def show_all_products_handler(callback: CallbackQuery):
    """Показать все товары"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    try:
        # Получаем все товары из базы данных
        products = db.get_all_products()
        
        if not products:
            builder = InlineKeyboardBuilder()
            builder.button(text="🏠 В главное меню", callback_data="back_to_main")
            builder.button(text="🔍 Поиск товаров", callback_data="search_products")
            builder.adjust(1)
            
            await callback.message.answer(
                "📦 <b>Все товары</b>\n\n"
                "❌ <b>В каталоге пока нет товаров.</b>\n\n"
                "Попробуйте позже или воспользуйтесь поиском.",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        if 'created_at' in products[0]:
            products.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Разбиваем товары на страницы (по 10 товаров на страницу)
        page_size = 10
        total_pages = (len(products) + page_size - 1) // page_size
        
        # Используем состояние для хранения текущей страницы
        user_state = get_user_state(callback.from_user.id)
        user_state.current_product_page = 0  # Начинаем с первой страницы
        user_state.all_products_list = products  # Сохраняем список товаров
        
        # Отображаем первую страницу
        await show_products_page(callback, products, 0, page_size, total_pages)
        
    except Exception as e:
        print(f"Error in show_all_products_handler: {e}")
        await callback.answer("Ошибка при загрузке товаров", show_alert=True)

async def show_products_page(
    callback: CallbackQuery, 
    products: List[Dict], 
    page: int, 
    page_size: int, 
    total_pages: int
) -> None:
    """Отобразить страницу с товарами"""
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(products))
    page_products = products[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки товаров
    for product in page_products:
        # Обрезаем длинные названия
        product_name = product['name']
        if len(product_name) > 35:
            product_name = product_name[:32] + "..."
        
        type_icon = "📅" if product.get('type') == 'preorder' else "✅"
        
        builder.button(
            text=f"{type_icon} {product_name} - {product['price']}",
            callback_data=f"product_{product['id']}"
        )
    
    # Добавляем кнопки навигации по страницам
    if total_pages > 1:
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="⬅️ Предыдущая",
                callback_data=f"all_products_page_{page-1}"
            ))
        
        nav_buttons.append(InlineKeyboardButton(
            text=f"📄 {page+1}/{total_pages}",
            callback_data="all_products_current"
        ))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Следующая ➡️",
                callback_data=f"all_products_page_{page+1}"
            ))
        
        builder.row(*nav_buttons)
    
    # Добавляем кнопки навигации
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    builder.adjust(1)
    
    # Формируем текст сообщения
    response_text = (
        f"📦 <b>Все товары</b>\n\n"
        f"<b>Всего товаров:</b> {len(products)}\n"
        f"<b>Страница:</b> {page+1}/{total_pages}\n\n"
        f"<b>Доступные товары:</b>\n"
    )
    
    # Добавляем информацию о товарах на странице
    for i, product in enumerate(page_products, start=start_idx+1):
        type_name = "📅 Предзаказ" if product.get('type') == 'preorder' else "✅ В наличии"
        category_name = db.get_category_name(product.get('category_slug', '')) or "Без категории"
        
        response_text += (
            f"{i}. <b>{product['name']}</b>\n"
            f"   💰 {product['price']} | {type_name}\n"
            f"   📂 {category_name}\n\n"
        )
    
    await callback.message.answer(
        response_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('all_products_page_'))
async def handle_all_products_page(callback: CallbackQuery):
    """Обработчик переключения страниц всех товаров"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    try:
        page = int(callback.data.replace('all_products_page_', ''))
        user_state = get_user_state(callback.from_user.id)
        
        if not hasattr(user_state, 'all_products_list') or not user_state.all_products_list:
            # Если список товаров не сохранен, получаем заново
            products = db.get_all_products()
            user_state.all_products_list = products
        else:
            products = user_state.all_products_list
        
        if not products:
            await callback.answer("Нет товаров для отображения", show_alert=True)
            return
        
        page_size = 10
        total_pages = (len(products) + page_size - 1) // page_size
        
        # Проверяем, что запрашиваемая страница существует
        if page < 0 or page >= total_pages:
            await callback.answer("Страница не существует", show_alert=True)
            return
        
        # Обновляем текущую страницу
        user_state.current_product_page = page
        
        # Удаляем предыдущее сообщение
        await delete_previous_message(callback)
        
        # Отображаем новую страницу
        await show_products_page(callback, products, page, page_size, total_pages)
        
    except Exception as e:
        print(f"Error in handle_all_products_page: {e}")
        await callback.answer("Ошибка при переключении страницы", show_alert=True)

@dp.callback_query(F.data == 'all_products_current')
async def handle_all_products_current(callback: CallbackQuery):
    """Обработчик текущей страницы"""
    await callback.answer(f"Текущая страница", show_alert=False)

@dp.message(Command('allproducts'))
async def allproducts_command(message: Message):
    """Команда /allproducts - показать все товары"""
    # Обновляем активность
    db.update_user_activity(message.from_user.id)
    
    # Проверяем бан
    if db.is_user_banned(message.from_user.id):
        await message.answer(
            "🚫 <b>Доступ запрещен</b>\n\n"
            "Вы были заблокированы администратором.",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        # Получаем все товары из базы данных
        products = db.get_all_products()
        
        if not products:
            builder = InlineKeyboardBuilder()
            builder.button(text="🏠 В главное меню", callback_data="back_to_main")
            builder.button(text="🔍 Поиск товаров", callback_data="search_products")
            builder.adjust(1)
            
            await message.answer(
                "📦 <b>Все товары</b>\n\n"
                "❌ <b>В каталоге пока нет товаров.</b>\n\n"
                "Попробуйте позже или воспользуйтесь поиском.",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        # Разбиваем товары на страницы (по 10 товаров на страницу)
        page_size = 10
        total_pages = (len(products) + page_size - 1) // page_size
        
        # Используем состояние для хранения текущей страницы
        user_state = get_user_state(message.from_user.id)
        user_state.current_product_page = 0
        user_state.all_products_list = products
        
        # Отображаем первую страницу
        start_idx = 0
        end_idx = min(page_size, len(products))
        page_products = products[start_idx:end_idx]
        
        builder = InlineKeyboardBuilder()
        
        # Добавляем кнопки товаров
        for product in page_products:
            product_name = product['name']
            if len(product_name) > 35:
                product_name = product_name[:32] + "..."
            
            type_icon = "📅" if product.get('type') == 'preorder' else "✅"
            
            builder.button(
                text=f"{type_icon} {product_name} - {product['price']}",
                callback_data=f"product_{product['id']}"
            )
        
        # Добавляем кнопки навигации по страницам
        if total_pages > 1:
            builder.button(text="Следующая страница ➡️", callback_data="all_products_page_1")
        
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        builder.button(text="🔍 Поиск товаров", callback_data="search_products")
        builder.adjust(1)
        
        # Формируем текст сообщения
        response_text = (
            f"📦 <b>Все товары</b>\n\n"
            f"<b>Всего товаров:</b> {len(products)}\n"
            f"<b>Страница:</b> 1/{total_pages}\n\n"
            f"<b>Доступные товары:</b>\n"
        )
        
        for i, product in enumerate(page_products, 1):
            type_name = "📅 Предзаказ" if product.get('type') == 'preorder' else "✅ В наличии"
            category_name = db.get_category_name(product.get('category_slug', '')) or "Без категории"
            
            response_text += (
                f"{i}. <b>{product['name']}</b>\n"
                f"   💰 {product['price']} | {type_name}\n"
                f"   📂 {category_name}\n\n"
            )
        
        await message.answer(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Error in allproducts_command: {e}")
        await message.answer(
            "❌ <b>Ошибка при загрузке товаров</b>\n\n"
            "Попробуйте позже или обратитесь в поддержку.",
            parse_mode=ParseMode.HTML
        )

@dp.callback_query(F.data == 'search_products')
async def search_products_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки поиска товаров"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    await callback.message.answer(
        "🔍 <b>Поиск товаров</b>\n\n"
        "Введите ключевые слова для поиска товаров:\n"
        "<i>Пример: funko, lego, танк, fnaf, наруто</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_search_query)

@dp.message(AdminStates.waiting_for_search_query)
async def process_search_query(message: Message, state: FSMContext):
    """Обработчик ввода поискового запроса"""
    # Проверяем бан
    if db.is_user_banned(message.from_user.id):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nВы были заблокированы администратором.", parse_mode=ParseMode.HTML)
        await state.clear()
        return
    
    # Обновляем активность
    db.update_user_activity(message.from_user.id)
    
    search_query = message.text.strip()
    
    if not search_query or len(search_query) < 2:
        await message.answer("❌ <b>Слишком короткий запрос</b>\n\nВведите хотя бы 2 символа для поиска.", parse_mode=ParseMode.HTML)
        return
    
    await message.answer(f"🔍 <b>Ищем товары по запросу:</b> <code>{search_query}</code>", parse_mode=ParseMode.HTML)
    
    # Ищем товары
    products = db.search_products(search_query)
    
    if not products:
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        builder.button(text="🔍 Новый поиск", callback_data="search_products")
        builder.adjust(1)
        
        await message.answer(
            f"❌ <b>По запросу \"{search_query}\" ничего не найдено</b>\n\n"
            "Попробуйте:\n"
            "• Использовать другие ключевые слова\n"
            "• Проверить правильность написания\n"
            "• Посмотреть все товары в каталоге",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        await state.clear()
        return
    
    # Группируем товары по категориям
    products_by_category = {}
    for product in products:
        category_slug = product['category_slug']
        if category_slug not in products_by_category:
            category_name = db.get_category_name(category_slug) or "Без категории"
            products_by_category[category_slug] = {
                'name': category_name,
                'products': []
            }
        products_by_category[category_slug]['products'].append(product)
    
    # Отправляем результаты поиска
    response_text = f"✅ <b>Найдено товаров:</b> {len(products)}\n<b>По запросу:</b> <code>{search_query}</code>\n\n"
    
    for category_slug, category_data in products_by_category.items():
        response_text += f"<b>{category_data['name']}</b>\n"
        
        for product in category_data['products'][:10]:
            product_name = product['name']
            if len(product_name) > 40:
                product_name = product_name[:37] + "..."
            
            type_icon = "📅" if product['type'] == 'preorder' else "✅"
            response_text += f"• {type_icon} {product_name} - {product['price']} "
            response_text += f"<code>/product_{product['id']}</code>\n"
        
        if len(category_data['products']) > 10:
            response_text += f"<i>... и ещё {len(category_data['products']) - 10} товаров</i>\n"
        
        response_text += "\n"
    
    # Создаем клавиатуру с кнопками товаров
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для товаров (первые 8)
    for product in products[:8]:
        product_name = product['name']
        if len(product_name) > 25:
            product_name = product_name[:22] + "..."
        
        builder.button(
            text=f"{product_name} - {product['price']}",
            callback_data=f"product_{product['id']}"
        )
    
    # Добавляем кнопки навигации
    if len(products) > 8:
        builder.button(text="📋 Показать все товары", callback_data=f"show_all_search_{search_query}")
    
    builder.button(text="🔍 Новый поиск", callback_data="search_products")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    
    # Настраиваем расположение кнопок
    builder.adjust(1, 1, 1)
    
    await message.answer(
        response_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.clear()

@dp.callback_query(F.data.startswith('show_all_search_'))
async def show_all_search_results(callback: CallbackQuery):
    """Показать все результаты поиска"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    search_query = callback.data.replace('show_all_search_', '')
    
    # Ищем товары
    products = db.search_products(search_query)
    
    if not products:
        await callback.answer("Товары не найдены", show_alert=True)
        return
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    # Создаем клавиатуру со всеми товарами
    builder = InlineKeyboardBuilder()
    
    for product in products:
        product_name = product['name']
        if len(product_name) > 35:
            product_name = product_name[:32] + "..."
        
        type_icon = "📅" if product['type'] == 'preorder' else "✅"
        
        builder.button(
            text=f"{type_icon} {product_name} - {product['price']}",
            callback_data=f"product_{product['id']}"
        )
    
    builder.button(text="⬅️ Назад к результатам", callback_data=f"back_to_search_{search_query}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    
    builder.adjust(1)
    
    await callback.message.answer(
        f"📋 <b>Все найденные товары</b>\n"
        f"<b>Запрос:</b> <code>{search_query}</code>\n"
        f"<b>Найдено:</b> {len(products)} товаров\n\n"
        "Выберите товар для просмотра:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('back_to_search_'))
async def back_to_search_results(callback: CallbackQuery):
    """Вернуться к результатам поиска"""
    # Проверяем бан
    if db.is_user_banned(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Обновляем активность
    db.update_user_activity(callback.from_user.id)
    
    search_query = callback.data.replace('back_to_search_', '')
    
    # Ищем товары
    products = db.search_products(search_query)
    
    if not products:
        await callback.answer("Товары не найдены", show_alert=True)
        return
    
    # Удаляем предыдущее сообщение
    await delete_previous_message(callback)
    
    # Отправляем результаты поиска
    response_text = f"✅ <b>Найдено товаров:</b> {len(products)}\n<b>По запросу:</b> <code>{search_query}</code>\n\n"
    
    # Группируем товары по категориям
    products_by_category = {}
    for product in products:
        category_slug = product['category_slug']
        if category_slug not in products_by_category:
            category_name = db.get_category_name(category_slug) or "Без категории"
            products_by_category[category_slug] = {
                'name': category_name,
                'products': []
            }
        products_by_category[category_slug]['products'].append(product)
    
    for category_slug, category_data in products_by_category.items():
        response_text += f"<b>{category_data['name']}</b>\n"
        
        for product in category_data['products'][:10]:
            product_name = product['name']
            if len(product_name) > 40:
                product_name = product_name[:37] + "..."
            
            type_icon = "📅" if product['type'] == 'preorder' else "✅"
            response_text += f"• {type_icon} {product_name} - {product['price']} "
            response_text += f"<code>/product_{product['id']}</code>\n"
        
        if len(category_data['products']) > 10:
            response_text += f"<i>... и ещё {len(category_data['products']) - 10} товаров</i>\n"
        
        response_text += "\n"
    
    builder = InlineKeyboardBuilder()
    
    for product in products[:8]:
        product_name = product['name']
        if len(product_name) > 25:
            product_name = product_name[:22] + "..."
        
        builder.button(
            text=f"{product_name} - {product['price']}",
            callback_data=f"product_{product['id']}"
        )
    
    if len(products) > 8:
        builder.button(text="📋 Показать все товары", callback_data=f"show_all_search_{search_query}")
    
    builder.button(text="🔍 Новый поиск", callback_data="search_products")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    
    builder.adjust(1, 1, 1)
    
    await callback.message.answer(
        response_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.message(Command('catalog'))
async def catalog_command(message: Message):
    """Команда /catalog"""
    # Обновляем активность
    db.update_user_activity(message.from_user.id)
    
    # Вызываем обработчик главного меню
    categories = db.get_categories()
    
    if not categories:
        await message.answer(
            "🌟 <b>Рады приветствовать тебя в боте «AsiaHappy»</b> 🌟\n\n"
            "Каталог товаров временно недоступен.\n"
            "Пожалуйста, попробуйте позже.",
            parse_mode=ParseMode.HTML
        )
        return
    
    builder = InlineKeyboardBuilder()
    
    for slug, name in categories.items():
        builder.button(text=name, callback_data=f"category_{slug}")
    
    # Добавляем кнопки помощи и поиска
    builder.button(text="🆘 Помощь / Справка", callback_data="show_help")
    builder.button(text="🔍 Поиск товаров", callback_data="search_products")
    
    builder.adjust(1)
    
    await message.answer(
        "🌟 <b>Рады приветствовать тебя в боте «AsiaHappy»</b> 🌟\n\n"
        "<i>Магазин коллекционных товаров: Funko Pop, конструкторы Lego и аналоги</i>\n\n"
        "👨‍💼 <b>Менеджер:</b> @AsiaHappyManager\n\n"
        "Доступные команды:\n"
        "• /help - Помощь и справка\n"
        "• /catalog - Открыть каталог\n\n"
        "Выберите категорию товаров:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

# ==================== АДМИН КОМАНДЫ ====================

@dp.message(Command('admin'))
async def admin_panel(message: Message):
    """Админ панель - доступ только для админов"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    admin_text = (
        "👑 <b>Админ-панель AsiaHappy</b>\n\n"
        "<b>Доступные команды:</b>\n"
        
        "📊 <b>Статистика:</b>\n"
        "• /stat - Общая статистика\n"
        "• /DBstat - Детальная статистика БД\n"
        "• /listbanned - Список забаненных\n\n"

        "📢 <b>Рассылки:</b>\n"
        "• /broadcast - Сделать рассылку всем пользователям\n\n"
        
        "🔄 <b>Управление системой:</b>\n"
        "• /reloadBD - Перезагрузить базу данных\n"
        "• /reloadBot - Перезагрузить бота\n"
        "• /ban [username] - Забанить пользователя\n"
        "• /unban [username] - Разбанить пользователя\n\n"
        
        "📂 <b>Управление категориями:</b>\n"
        "• /addcategory - Добавить категорию\n"
        "• /editcategory - Изменить категорию\n"
        "• /delcategory - Удалить категорию\n\n"
        
        "📚 <b>Управление подкатегориями:</b>\n"
        "• /addsubcategory - Добавить подкатегорию\n"
        "• /editsubcategory - Изменить подкатегорию\n"
        "• /delsubcategory - Удалить подкатегорию\n\n"
        
        "📦 <b>Управление товарами:</b>\n"
        "• /addproduct - Добавить товар\n"
        "• /editproduct - Изменить товар\n"
        "• /delproduct - Удалить товар\n\n"
        
        "🔍 <b>Поиск:</b>\n"
        "• /search - Поиск товаров по ключевым словам (только для админов)\n\n"
        
        "<i>Для выполнения команд используйте соответствующие команды из списка выше.</i>"
    )
    
    await message.answer(admin_text, parse_mode=ParseMode.HTML)

# ==================== АДМИН КОМАНДЫ - СТАТИСТИКА ====================

@dp.message(Command('stat'))
async def show_statistics(message: Message):
    """Показать общую статистику"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    stats = db.get_overall_stats()
    
    response = "📊 <b>Общая статистика бота AsiaHappy</b>\n\n"
    
    response += f"👥 <b>Пользователи:</b>\n"
    response += f"• Всего пользователей: {stats.get('total_users', 0)}\n"
    response += f"• Активных за 24 часа: {stats.get('active_users_24h', 0)}\n"
    response += f"• Онлайн сейчас: {stats.get('online_now', 0)}\n"
    response += f"• Забанено: {stats.get('banned_users', 0)}\n\n"
    
    response += f"📦 <b>Товары:</b>\n"
    response += f"• Всего товаров: {stats.get('total_products', 0)}\n"
    response += f"• Категорий: {stats.get('total_categories', 0)}\n"
    response += f"• Подкатегорий: {stats.get('total_subcategories', 0)}\n"
    response += f"• Всего кликов: {stats.get('total_clicks', 0)}\n\n"
    
    # Товары по типам
    if 'products_by_type' in stats:
        response += f"📋 <b>Товары по типам:</b>\n"
        for type_, count in stats['products_by_type'].items():
            type_name = "✅ В наличии" if type_ == 'instock' else "📅 Предзаказ"
            response += f"• {type_name}: {count}\n"
        response += "\n"
    
    # Самые активные пользователи
    if 'top_users' in stats and stats['top_users']:
        response += f"🏆 <b>Топ-5 активных пользователей:</b>\n"
        for i, (username, first_name, total_clicks, product_clicks, last_seen) in enumerate(stats['top_users'][:5], 1):
            name = f"@{username}" if username else first_name or "Без имени"
            response += f"{i}. {name} - {total_clicks} кликов ({product_clicks} по товарам)\n"
        response += "\n"
    
    # Самые популярные товары
    if 'top_products' in stats and stats['top_products']:
        response += f"🔥 <b>Топ-5 популярных товаров:</b>\n"
        for i, (product_id, name, category_slug, subcategory_slug, clicks, last_click) in enumerate(stats['top_products'][:5], 1):
            response += f"{i}. {name} - {clicks} кликов\n"
    
    await message.answer(response, parse_mode=ParseMode.HTML)

@dp.message(Command('DBstat'))
async def show_detailed_statistics(message: Message):
    """Показать детальную статистику БД"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    stats = db.get_detailed_database_stats()
    
    response = "📋 <b>Детальная статистика базы данных</b>\n\n"
    
    response += f"🔧 <b>Общая информация:</b>\n"
    response += f"• Версия БД: {stats.get('db_version', 'Неизвестно')}\n"
    response += f"• Категорий: {stats.get('total_categories', 0)}\n"
    response += f"• Подкатегорий: {stats.get('total_subcategories', 0)}\n"
    response += f"• Товаров: {stats.get('total_products', 0)}\n"
    response += f"• Пользователей: {stats.get('total_users', 0)}\n"
    response += f"• Забанено: {stats.get('banned_users', 0)}\n"
    response += f"• Всего кликов: {stats.get('total_clicks', 0)}\n\n"
    
    # Категории
    if 'categories' in stats and stats['categories']:
        response += f"📂 <b>Категории ({len(stats['categories'])}):</b>\n"
        for i, (cat_id, slug, name, created_at) in enumerate(stats['categories'][:10], 1):
            response += f"{i}. {name} ({slug}) - ID: {cat_id}\n"
        if len(stats['categories']) > 10:
            response += f"... и ещё {len(stats['categories']) - 10} категорий\n"
        response += "\n"
    
    # Подкатегории
    if 'subcategories' in stats and stats['subcategories']:
        response += f"📚 <b>Подкатегории ({len(stats['subcategories'])}):</b>\n"
        for i, (subcat_id, name, slug, type_, category_name, created_at) in enumerate(stats['subcategories'][:10], 1):
            type_display = "✅ В наличии" if type_ == 'instock' else "📅 Предзаказ"
            response += f"{i}. {name} ({slug}) - {category_name} - {type_display}\n"
        if len(stats['subcategories']) > 10:
            response += f"... и ещё {len(stats['subcategories']) - 10} подкатегорий\n"
        response += "\n"
    
    # Товары
    if 'products' in stats and stats['products']:
        response += f"📦 <b>Товары ({len(stats['products'])}):</b>\n"
        for i, (prod_id, name, category_slug, subcategory_slug, type_, price, created_at, updated_at, clicks) in enumerate(stats['products'][:10], 1):
            type_display = "✅ В наличии" if type_ == 'instock' else "📅 Предзаказ"
            response += f"{i}. {name} - {price} ({type_display}) - {clicks} кликов\n"
        if len(stats['products']) > 10:
            response += f"... и ещё {len(stats['products']) - 10} товаров\n"
        response += "\n"
    
    # Пользователи
    if 'users' in stats and stats['users']:
        response += f"👥 <b>Пользователи ({len(stats['users'])}):</b>\n"
        for i, (user_id, username, first_name, last_name, is_banned, first_seen, last_seen, total_clicks, product_clicks) in enumerate(stats['users'][:10], 1):
            name = f"@{username}" if username else first_name or f"ID: {user_id}"
            banned = "🚫" if is_banned else "✅"
            response += f"{i}. {name} {banned} - {total_clicks} кликов\n"
        if len(stats['users']) > 10:
            response += f"... и ещё {len(stats['users']) - 10} пользователей\n"
    
    await message.answer(response, parse_mode=ParseMode.HTML)

@dp.message(Command('listbanned'))
async def list_banned_users(message: Message):
    """Список забаненных пользователей"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    stats = db.get_detailed_database_stats()
    
    if 'users' not in stats or not stats['users']:
        await message.answer("📋 <b>Список забаненных пользователей</b>\n\nВ базе данных нет пользователей.", parse_mode=ParseMode.HTML)
        return
    
    banned_users = []
    for user in stats['users']:
        user_id, username, first_name, last_name, is_banned = user[:5]
        if is_banned:
            banned_users.append(user)
    
    if not banned_users:
        await message.answer("📋 <b>Список забаненных пользователей</b>\n\nНет забаненных пользователей.", parse_mode=ParseMode.HTML)
        return
    
    response = "🚫 <b>Забаненные пользователи</b>\n\n"
    
    for i, (user_id, username, first_name, last_name, is_banned, first_seen, last_seen, total_clicks, product_clicks) in enumerate(banned_users, 1):
        name = f"@{username}" if username else f"{first_name or ''} {last_name or ''}".strip() or f"ID: {user_id}"
        response += f"{i}. <b>{name}</b>\n"
        response += f"   ID: {user_id}\n"
        if first_name or last_name:
            response += f"   Имя: {first_name or ''} {last_name or ''}\n"
        response += f"   Первый вход: {first_seen}\n"
        response += f"   Последняя активность: {last_seen}\n"
        response += f"   Кликов: {total_clicks}\n\n"
    
    await message.answer(response, parse_mode=ParseMode.HTML)

# ==================== АДМИН КОМАНДЫ - УПРАВЛЕНИЕ СИСТЕМОЙ ====================

@dp.message(Command('reloadBD'))
async def reload_database(message: Message):
    """Перезагрузка базы данных (без очистки данных)"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    await message.answer("🔄 <b>Перезагрузка базы данных...</b>\n\n<i>Это может занять несколько секунд. Данные не будут удалены.</i>", parse_mode=ParseMode.HTML)
    
    # Получаем статистику до перезагрузки
    stats_before = db.get_overall_stats()
    
    success = db.reload_database()
    
    if success:
        # Получаем статистику после перезагрузки
        stats_after = db.get_overall_stats()
        
        response = "✅ <b>База данных успешно перезагружена!</b>\n\n"
        response += "📊 <b>Статистика до/после:</b>\n"
        
        # Сравниваем статистику
        fields_to_compare = [
            ('total_users', '👥 Пользователей'),
            ('total_products', '📦 Товаров'),
            ('total_categories', '📂 Категорий'),
            ('total_subcategories', '📚 Подкатегорий'),
            ('total_clicks', '🖱️ Кликов')
        ]
        
        for field, name in fields_to_compare:
            before = stats_before.get(field, 0)
            after = stats_after.get(field, 0)
            
            if before == after:
                response += f"• {name}: {before} → {after} (без изменений)\n"
            elif after > before:
                response += f"• {name}: {before} → {after} (+{after - before})\n"
            else:
                response += f"• {name}: {before} → {after} (-{before - after})\n"
        
        response += "\n🔄 <b>Выполнены следующие действия:</b>\n"
        response += "• Проверена структура базы данных\n"
        response += "• Обновлены таблицы при необходимости\n"
        response += "• Проверена целостность данных\n"
        response += "• Создана резервная копия\n"
        
        # Проверяем целостность
        integrity = db.check_integrity()
        if integrity['status'] == 'ok':
            response += "\n✅ <b>Целостность базы данных в порядке</b>"
        else:
            response += f"\n⚠️ <b>Обнаружены проблемы с целостностью:</b>\n"
            for error in integrity.get('errors', [])[:3]:
                response += f"• ❌ {error}\n"
            for warning in integrity.get('warnings', [])[:3]:
                response += f"• ⚠️ {warning}\n"
        
        await message.answer(response, parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            "❌ <b>Ошибка при перезагрузке базы данных</b>\n\n"
            "База данных была восстановлена из резервной копии.\n"
            "Обратитесь к разработчику для решения проблемы.",
            parse_mode=ParseMode.HTML
        )

@dp.message(Command('reloadBot'))
async def reload_bot(message: Message):
    """Перезагрузка бота"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    await message.answer("🔄 <b>Бот будет перезагружен...</b>", parse_mode=ParseMode.HTML)
    
    # Отправляем команду на перезагрузку
    os.kill(os.getpid(), signal.SIGTERM)

@dp.message(Command('ban'))
async def ban_user_start(message: Message, state: FSMContext):
    """Начало бана пользователя"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Пытаемся получить username из команды
    command_parts = message.text.split()
    if len(command_parts) >= 2:
        username = command_parts[1]
        # Пробуем забанить сразу
        success = db.ban_user(username)
        if success:
            await message.answer(f"✅ <b>Пользователь @{username.lstrip('@')} забанен!</b>", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ <b>Не удалось забанить пользователя @{username.lstrip('@')}</b>\n\nПользователь не найден в базе данных.", parse_mode=ParseMode.HTML)
        return
    
    # Если username не указан, запрашиваем его
    await message.answer(
        "🚫 <b>Бан пользователя</b>\n\n"
        "Введите username пользователя для бана (с @ или без):\n"
        "<i>Пример: @username или username</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_username_to_ban)

@dp.message(AdminStates.waiting_for_username_to_ban)
async def ban_user_process(message: Message, state: FSMContext):
    """Бан пользователя"""
    username = message.text.strip()
    
    if not username:
        await message.answer("❌ <b>Не указан username</b>\n\nВведите username пользователя.", parse_mode=ParseMode.HTML)
        return
    
    success = db.ban_user(username)
    
    if success:
        await message.answer(f"✅ <b>Пользователь @{username.lstrip('@')} забанен!</b>", parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"❌ <b>Не удалось забанить пользователя @{username.lstrip('@')}</b>\n\n"
            "Возможные причины:\n"
            "• Пользователь не найден в базе данных\n"
            "• Пользователь уже забанен\n"
            "• Ошибка базы данных",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command('unban'))
async def unban_user_start(message: Message, state: FSMContext):
    """Начало разбана пользователя"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Пытаемся получить username из команды
    command_parts = message.text.split()
    if len(command_parts) >= 2:
        username = command_parts[1]
        # Пробуем разбанить сразу
        success = db.unban_user(username)
        if success:
            await message.answer(f"✅ <b>Пользователь @{username.lstrip('@')} разбанен!</b>", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ <b>Не удалось разбанить пользователя @{username.lstrip('@')}</b>\n\nПользователь не найден в базе данных или не был забанен.", parse_mode=ParseMode.HTML)
        return
    
    # Если username не указан, запрашиваем его
    await message.answer(
        "🔄 <b>Разбан пользователя</b>\n\n"
        "Введите username пользователя для разбана (с @ или без):\n"
        "<i>Пример: @username или username</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_username_to_unban)

@dp.message(AdminStates.waiting_for_username_to_unban)
async def unban_user_process(message: Message, state: FSMContext):
    """Разбан пользователя"""
    username = message.text.strip()
    
    if not username:
        await message.answer("❌ <b>Не указан username</b>\n\nВведите username пользователя.", parse_mode=ParseMode.HTML)
        return
    
    success = db.unban_user(username)
    
    if success:
        await message.answer(f"✅ <b>Пользователь @{username.lstrip('@')} разбанен!</b>", parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"❌ <b>Не удалось разбанить пользователя @{username.lstrip('@')}</b>\n\n"
            "Возможные причины:\n"
            "• Пользователь не найден в базе данных\n"
            "• Пользователь не был забанен\n"
            "• Ошибка базы данных",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

# ==================== АДМИН КОМАНДЫ - РАССЫЛКА ====================
@dp.message(Command('broadcast'))
async def broadcast_start(message: Message, state: FSMContext):
    """Начало рассылки сообщений всем пользователям"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем статистику пользователей
    stats = db.get_overall_stats()
    total_users = stats.get('total_users', 0)
    active_users = stats.get('active_users_24h', 0)
    banned_users = stats.get('banned_users', 0)
    
    # Вычисляем количество пользователей для рассылки
    users_to_broadcast = total_users - banned_users
    
    await message.answer(
        f"📢 <b>Создание рассылки</b>\n\n"
        f"📊 <b>Статистика пользователей:</b>\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Забанено: {banned_users}\n"
        f"• Активных за 24 часа: {active_users}\n"
        f"• Получат рассылку: {users_to_broadcast}\n\n"
        f"<b>⚠️ Внимание:</b> Рассылка будет отправлена всем пользователям, кроме забаненных.\n\n"
        f"Отправьте сообщение для рассылки (текст, фото, видео, документ):\n"
        f"<i>Можно использовать HTML-разметку для форматирования</i>",
        parse_mode=ParseMode.HTML
    )
    
    # Сохраняем информацию о пользователе, который делает рассылку
    await state.update_data(
        admin_id=message.from_user.id,
        admin_username=message.from_user.username,
        total_users=total_users,
        banned_users=banned_users,
        users_to_broadcast=users_to_broadcast
    )
    
    await state.set_state(AdminStates.waiting_for_broadcast_message)

@dp.message(AdminStates.waiting_for_broadcast_message)
async def broadcast_message_received(message: Message, state: FSMContext):
    """Получение сообщения для рассылки"""
    data = await state.get_data()
    
    # Сохраняем сообщение в состоянии
    message_type = None
    message_content = None
    caption = None
    parse_mode = None
    
    if message.text:
        message_type = 'text'
        message_content = message.text
        parse_mode = message.parse_mode if message.parse_mode else ParseMode.HTML
    
    elif message.photo:
        message_type = 'photo'
        message_content = message.photo[-1].file_id
        caption = message.caption
        parse_mode = message.parse_mode if message.parse_mode else ParseMode.HTML
    
    elif message.video:
        message_type = 'video'
        message_content = message.video.file_id
        caption = message.caption
        parse_mode = message.parse_mode if message.parse_mode else ParseMode.HTML
    
    elif message.document:
        message_type = 'document'
        message_content = message.document.file_id
        caption = message.caption
        parse_mode = message.parse_mode if message.parse_mode else ParseMode.HTML
    
    else:
        await message.answer(
            "❌ <b>Неподдерживаемый тип сообщения</b>\n\n"
            "Поддерживаются: текст, фото, видео, документы.\n"
            "Попробуйте еще раз.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Сохраняем сообщение в состоянии
    await state.update_data(
        message_type=message_type,
        message_content=message_content,
        caption=caption,
        parse_mode=parse_mode,
        original_message_id=message.message_id
    )
    
    # Создаем превью сообщения
    preview_text = "📢 <b>ПРЕВЬЮ РАССЫЛКИ</b>\n\n"
    
    if message_type == 'text':
        preview_text += f"📝 <b>Текст:</b>\n{message_content[:500]}"
        if len(message_content) > 500:
            preview_text += "..."
    elif message_type == 'photo':
        preview_text += "🖼️ <b>Фото с подписью:</b>\n"
        if caption:
            preview_text += f"{caption[:500]}"
            if len(caption) > 500:
                preview_text += "..."
        else:
            preview_text += "Без подписи"
    elif message_type == 'video':
        preview_text += "🎬 <b>Видео с подписью:</b>\n"
        if caption:
            preview_text += f"{caption[:500]}"
            if len(caption) > 500:
                preview_text += "..."
        else:
            preview_text += "Без подписи"
    elif message_type == 'document':
        preview_text += "📎 <b>Документ с подписью:</b>\n"
        if caption:
            preview_text += f"{caption[:500]}"
            if len(caption) > 500:
                preview_text += "..."
        else:
            preview_text += "Без подписи"
    
    preview_text += f"\n\n📊 <b>Будет отправлено:</b> {data.get('users_to_broadcast', 0)} пользователям"
    
    # Создаем кнопки подтверждения
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Начать рассылку", callback_data="broadcast_confirm")
    builder.button(text="❌ Отменить", callback_data="broadcast_cancel")
    builder.adjust(1)
    
    # Отправляем превью
    if message_type == 'text':
        await message.answer(preview_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    else:
        # Отправляем оригинальное сообщение с кнопками
        if caption:
            await message.answer(preview_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        else:
            # Если нет подписи, отправляем отдельное сообщение с превью
            await message.answer(preview_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    
    await state.set_state(AdminStates.waiting_for_broadcast_confirmation)

@dp.callback_query(F.data == 'broadcast_confirm', AdminStates.waiting_for_broadcast_confirmation)
async def broadcast_confirm_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение и начало рассылки"""
    data = await state.get_data()
    
    # Получаем данные о рассылке
    users_to_broadcast = data.get('users_to_broadcast', 0)
    message_type = data.get('message_type')
    message_content = data.get('message_content')
    caption = data.get('caption')
    parse_mode = data.get('parse_mode', ParseMode.HTML)
    admin_id = data.get('admin_id')
    
    if users_to_broadcast <= 0:
        await callback.answer("Нет пользователей для рассылки", show_alert=True)
        await state.clear()
        return
    
    # Обновляем статус в сообщении
    await callback.message.edit_text(
        f"🔄 <b>Начинаем рассылку...</b>\n\n"
        f"📊 <b>Всего пользователей:</b> {users_to_broadcast}\n"
        f"⏳ <b>Статус:</b> Подготовка\n"
        f"✅ <b>Отправлено:</b> 0/{users_to_broadcast}\n"
        f"❌ <b>Ошибок:</b> 0",
        parse_mode=ParseMode.HTML
    )
    
    # Получаем всех пользователей из базы данных
    users = db.get_all_users_for_broadcast()
    
    if not users:
        await callback.message.edit_text(
            "❌ <b>Ошибка: не найдены пользователи для рассылки</b>",
            parse_mode=ParseMode.HTML
        )
        await state.clear()
        return
    
    success_count = 0
    failed_count = 0
    skipped_banned = 0
    
    # Отправляем сообщение каждому пользователю
    for i, user in enumerate(users, 1):
        user_id = user['user_id']
        
        # Пропускаем забаненных пользователей
        if user.get('is_banned', 0) == 1:
            skipped_banned += 1
            continue
        
        # Пропускаем админа, если это не он сам
        if user_id == admin_id:
            continue
        
        try:
            if message_type == 'text':
                await bot.send_message(
                    chat_id=user_id,
                    text=message_content,
                    parse_mode=parse_mode
                )
            elif message_type == 'photo':
                await bot.send_photo(
                    chat_id=user_id,
                    photo=message_content,
                    caption=caption,
                    parse_mode=parse_mode
                )
            elif message_type == 'video':
                await bot.send_video(
                    chat_id=user_id,
                    video=message_content,
                    caption=caption,
                    parse_mode=parse_mode
                )
            elif message_type == 'document':
                await bot.send_document(
                    chat_id=user_id,
                    document=message_content,
                    caption=caption,
                    parse_mode=parse_mode
                )
            
            success_count += 1
            
            # Обновляем статус каждые 10 отправок
            if i % 10 == 0 or i == len(users):
                try:
                    await callback.message.edit_text(
                        f"🔄 <b>Идет рассылка...</b>\n\n"
                        f"📊 <b>Всего пользователей:</b> {len(users)}\n"
                        f"⏳ <b>Статус:</b> Отправка...\n"
                        f"✅ <b>Отправлено:</b> {success_count}/{users_to_broadcast}\n"
                        f"❌ <b>Ошибок:</b> {failed_count}\n"
                        f"🚫 <b>Пропущено (бан):</b> {skipped_banned}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
            
            # Небольшая задержка, чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.1)
            
        except Exception as e:
            failed_count += 1
            print(f"Ошибка при отправке пользователю {user_id}: {e}")
            
            # Если пользователь заблокировал бота, отмечаем его как неактивного
            if "bot was blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                db.mark_user_inactive(user_id)
    
    # Завершаем рассылку
    final_message = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Всего пользователей: {len(users)}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Ошибок отправки: {failed_count}\n"
        f"• Пропущено (бан/админ): {skipped_banned + 1}\n\n"
    )
    
    if success_count == 0:
        final_message += "⚠️ <b>Рассылка не была отправлена ни одному пользователю.</b>\n"
        final_message += "Возможные причины:\n"
        final_message += "• Все пользователи забанены\n"
        final_message += "• Бот заблокирован у всех пользователей\n"
        final_message += "• Ошибка при отправке сообщений\n"
    elif failed_count > 0:
        final_message += f"⚠️ <b>Часть сообщений не была доставлена</b> ({failed_count} ошибок)\n"
        final_message += "Обычно это происходит, когда пользователи заблокировали бота.\n"
    
    final_message += f"\n👑 <b>Рассылка выполнена:</b> @{data.get('admin_username', 'admin')}"
    
    await callback.message.edit_text(final_message, parse_mode=ParseMode.HTML)
    
    # Отправляем отчет админу в личку
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=f"📊 <b>Отчет о рассылке</b>\n\n{final_message}",
            parse_mode=ParseMode.HTML
        )
    except:
        pass
    
    await state.clear()

@dp.callback_query(F.data == 'broadcast_cancel', AdminStates.waiting_for_broadcast_confirmation)
async def broadcast_cancel_handler(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await callback.message.edit_text(
        "❌ <b>Рассылка отменена</b>\n\n"
        "Сообщение не было отправлено пользователям.",
        parse_mode=ParseMode.HTML
    )
    
    await state.clear()

@dp.message(Command('broadcast_active'))
async def broadcast_active_start(message: Message, state: FSMContext):
    """Рассылка только активным пользователям (за последние 24 часа)"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем активных пользователей
    active_users = db.get_active_users_24h()
    
    await message.answer(
        f"📢 <b>Рассылка активным пользователям</b>\n\n"
        f"📊 <b>Активных пользователей (24ч):</b> {len(active_users)}\n\n"
        f"Отправьте сообщение для рассылки активным пользователям:",
        parse_mode=ParseMode.HTML
    )
    
    await state.update_data(
        admin_id=message.from_user.id,
        admin_username=message.from_user.username,
        users_to_broadcast=len(active_users),
        broadcast_type='active'
    )
    
    await state.set_state(AdminStates.waiting_for_broadcast_message)

# ==================== АДМИН КОМАНДЫ - УПРАВЛЕНИЕ КАТЕГОРИЯМИ ====================

@dp.message(Command('addcategory'))
async def add_category_start(message: Message, state: FSMContext):
    """Начало добавления категории"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    await message.answer(
        "📂 <b>Добавление новой категории</b>\n\n"
        "Введите название категории:\n"
        "<i>Пример: 🎮 Видеоигры, 📚 Книги, 🎭 Funko Pop</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_category_name)

@dp.message(AdminStates.waiting_for_category_name)
async def add_category_name(message: Message, state: FSMContext):
    """Получение названия категории"""
    category_name = message.text.strip()
    
    if not category_name or len(category_name) < 2:
        await message.answer("❌ <b>Название слишком короткое</b>\n\nВведите название категории (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    await state.update_data(category_name=category_name)
    
    await message.answer(
        f"✅ <b>Название сохранено:</b> {category_name}\n\n"
        "Теперь введите slug (идентификатор) для категории:\n"
        "<i>Пример: videogames, books, funko\n(только латинские буквы, цифры и дефисы, без пробелов)</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_category_slug)

@dp.message(AdminStates.waiting_for_category_slug)
async def add_category_slug(message: Message, state: FSMContext):
    """Получение slug категории"""
    slug = message.text.strip().lower()
    
    # Проверяем slug на корректность
    if not slug or len(slug) < 2:
        await message.answer("❌ <b>Slug слишком короткий</b>\n\nВведите slug (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    # Проверяем, что slug состоит только из латинских букв, цифр и дефисов
    if not re.match(r'^[a-z0-9\-]+$', slug):
        await message.answer(
            "❌ <b>Некорректный slug</b>\n\n"
            "Slug должен содержать только:\n"
            "• Латинские буквы (a-z)\n"
            "• Цифры (0-9)\n"
            "• Дефисы (-)\n"
            "<i>Пример: videogames, lego-sets, funko-pop</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем, не существует ли уже категория с таким slug
    categories = db.get_categories()
    if slug in categories:
        await message.answer(
            f"❌ <b>Категория с slug '{slug}' уже существует!</b>\n\n"
            f"Текущее название: {categories[slug]}\n"
            "Введите другой slug:",
            parse_mode=ParseMode.HTML
        )
        return
    
    data = await state.get_data()
    category_name = data.get('category_name', '')
    
    # Добавляем категорию в базу данных
    success = db.add_category(category_name, slug)
    
    if success:
        await message.answer(
            f"✅ <b>Категория успешно добавлена!</b>\n\n"
            f"📂 <b>Название:</b> {category_name}\n"
            f"🔗 <b>Slug:</b> {slug}\n\n"
            "Категория теперь доступна в главном меню.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении категории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command('editcategory'))
async def edit_category_start(message: Message, state: FSMContext):
    """Начало редактирования категории"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer("❌ <b>Нет категорий для редактирования</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for slug, name in categories.items():
        builder.button(text=f"{name} ({slug})", callback_data=f"editcat_{slug}")
    
    builder.adjust(1)
    
    # Сохраняем список категорий в состоянии
    await state.update_data(categories_dict=categories)
    
    await message.answer(
        "📂 <b>Редактирование категории</b>\n\n"
        "Выберите категорию для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
   

@dp.callback_query(F.data.startswith('editcat_'))
async def edit_category_select(callback: CallbackQuery, state: FSMContext):
    """Выбор категории для редактирования"""
    slug = callback.data.replace('editcat_', '')
    
    # Получаем категории из состояния или из БД
    data = await state.get_data()
    categories = data.get('categories_dict', db.get_categories())
    
    if slug not in categories:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    # Сохраняем выбранную категорию в состоянии
    await state.update_data(
        selected_category_slug=slug,
        selected_category_name=categories[slug],
        action='editing_category'
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Изменить название", callback_data=f"editname_{slug}")
    builder.button(text="🔗 Изменить slug", callback_data=f"editslug_{slug}")
    builder.button(text="❌ Отмена", callback_data="editcancel")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📂 <b>Редактирование категории</b>\n\n"
        f"<b>Текущее название:</b> {categories[slug]}\n"
        f"<b>Текущий slug:</b> {slug}\n\n"
        "Что вы хотите изменить?",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    

@dp.callback_query(F.data.startswith('editname_'))
async def edit_category_name_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения названия категории"""
    slug = callback.data.replace('editname_', '')
    
    # Сохраняем slug в состоянии
    await state.update_data(
        editing_category_slug=slug,
        edit_action='change_name'
    )
    
    # Устанавливаем состояние
    await state.set_state(AdminStates.waiting_for_new_category_name)
    
    # Получаем текущее название
    categories = db.get_categories()
    current_name = categories.get(slug, "Неизвестно")
    
    await callback.message.edit_text(
        f"📝 <b>Изменение названия категории</b>\n\n"
        f"Текущее название: <b>{current_name}</b>\n"
        f"Текущий slug: <b>{slug}</b>\n\n"
        "Введите новое название категории:",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith('editslug_'))
async def edit_category_slug_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения slug категории"""
    slug = callback.data.replace('editslug_', '')
    
    # Сохраняем slug в состоянии
    await state.update_data(
        editing_category_slug=slug,
        edit_action='change_slug'
    )
    
    # Устанавливаем состояние
    await state.set_state(AdminStates.waiting_for_new_category_slug)
    
    # Получаем текущее название
    categories = db.get_categories()
    current_name = categories.get(slug, "Неизвестно")
    
    await callback.message.edit_text(
        f"🔗 <b>Изменение slug категории</b>\n\n"
        f"Текущее название: <b>{current_name}</b>\n"
        f"Текущий slug: <b>{slug}</b>\n\n"
        "Введите новый slug (идентификатор) для категории:\n"
        "<i>Пример: videogames, books, funko\n(только латинские буквы, цифры и дефисы, без пробелов)</i>",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == 'editcancel')
async def edit_category_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования категории"""
    await callback.message.edit_text(
        "❌ <b>Редактирование категории отменено</b>",
        parse_mode=ParseMode.HTML
    )
    
    await state.clear()   

@dp.message(AdminStates.waiting_for_new_category_name)
async def edit_category_name_process(message: Message, state: FSMContext):
    """Обработка нового названия категории"""
    new_name = message.text.strip()
    
    if not new_name or len(new_name) < 2:
        await message.answer("❌ <b>Название слишком короткое</b>\n\nВведите название категории (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    old_slug = data.get('editing_category_slug')
    
    if not old_slug:
        await message.answer("❌ <b>Ошибка: не найдена категория для редактирования</b>\n\nНачните заново с /editcategory", parse_mode=ParseMode.HTML)
        await state.clear()
        return
    
    # Обновляем категорию
    success = db.update_category(old_slug, new_name=new_name)
    
    if success:
        await message.answer(
            f"✅ <b>Название категории успешно изменено!</b>\n\n"
            f"📂 <b>Старый slug:</b> {old_slug}\n"
            f"📂 <b>Новое название:</b> {new_name}",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при изменении категории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(AdminStates.waiting_for_new_category_slug)
async def edit_category_slug_process(message: Message, state: FSMContext):
    """Обработка нового slug категории"""
    new_slug = message.text.strip().lower()
    
    # Проверяем slug на корректность
    if not new_slug or len(new_slug) < 2:
        await message.answer("❌ <b>Slug слишком короткий</b>\n\nВведите slug (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    # Проверяем, что slug состоит только из латинских букв, цифр и дефисов
    if not re.match(r'^[a-z0-9\-]+$', new_slug):
        await message.answer(
            "❌ <b>Некорректный slug</b>\n\n"
            "Slug должен содержать только:\n"
            "• Латинские буквы (a-z)\n"
            "• Цифры (0-9)\n"
            "• Дефисы (-)\n"
            "<i>Пример: videogames, lego-sets, funko-pop</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    old_slug = data.get('editing_category_slug')
    
    if not old_slug:
        await message.answer("❌ <b>Ошибка: не найдена категория для редактирования</b>\n\nНачните заново с /editcategory", parse_mode=ParseMode.HTML)
        await state.clear()
        return
    
    # Проверяем, не существует ли уже категория с таким slug
    categories = db.get_categories()
    if new_slug in categories:
        await message.answer(
            f"❌ <b>Категория с slug '{new_slug}' уже существует!</b>\n\n"
            f"Текущее название: {categories[new_slug]}\n"
            "Введите другой slug:",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем старое название для отображения
    old_name = categories.get(old_slug, "Неизвестно")
    
    # Обновляем категорию
    success = db.update_category(old_slug, new_slug=new_slug)
    
    if success:
        await message.answer(
            f"✅ <b>Slug категории успешно изменен!</b>\n\n"
            f"📂 <b>Название:</b> {old_name}\n"
            f"🔗 <b>Старый slug:</b> {old_slug}\n"
            f"🔗 <b>Новый slug:</b> {new_slug}",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при изменении категории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

# ==================== АДМИН КОМАНДЫ - УПРАВЛЕНИЕ ПОДКАТЕГОРИЯМИ ====================

@dp.message(Command('addsubcategory'))
async def add_subcategory_start(message: Message, state: FSMContext):
    """Начало добавления подкатегории"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer("❌ <b>Нет категорий. Сначала добавьте категорию!</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for slug, name in categories.items():
        builder.button(text=name, callback_data=f"addsubcat_cat_{slug}")
    
    builder.adjust(1)
    
    await message.answer(
        "📚 <b>Добавление новой подкатегории</b>\n\n"
        "Выберите категорию для подкатегории:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_subcategory_category)

@dp.callback_query(F.data.startswith('addsubcat_cat_'), AdminStates.waiting_for_subcategory_category)
async def add_subcategory_select_category(callback: CallbackQuery, state: FSMContext):
    """Выбор категории для подкатегории"""
    category_slug = callback.data.replace('addsubcat_cat_', '')
    categories = db.get_categories()
    
    if category_slug not in categories:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    await state.update_data(category_slug=category_slug, category_name=categories[category_slug])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ В наличии", callback_data="addsubcat_type_instock")
    builder.button(text="📅 Предзаказ", callback_data="addsubcat_type_preorder")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📚 <b>Добавление подкатегории</b>\n\n"
        f"<b>Категория:</b> {categories[category_slug]}\n\n"
        "Выберите тип подкатегории:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_subcategory_type)

@dp.callback_query(F.data.startswith('addsubcat_type_'), AdminStates.waiting_for_subcategory_type)
async def add_subcategory_select_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа подкатегории"""
    type_ = callback.data.replace('addsubcat_type_', '')
    type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
    
    if type_ not in type_names:
        await callback.answer("Некорректный тип", show_alert=True)
        return
    
    await state.update_data(type=type_)
    
    await callback.message.edit_text(
        f"📚 <b>Добавление подкатегории</b>\n\n"
        f"<b>Тип:</b> {type_names[type_]}\n\n"
        "Введите название подкатегории:\n"
        "<i>Пример: 🎬 Фильмы, 🎮 Игры, 🇯🇵 Аниме</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_subcategory_name)

@dp.message(AdminStates.waiting_for_subcategory_name)
async def add_subcategory_name(message: Message, state: FSMContext):
    """Получение названия подкатегории"""
    subcategory_name = message.text.strip()
    
    if not subcategory_name or len(subcategory_name) < 2:
        await message.answer("❌ <b>Название слишком короткое</b>\n\nВведите название подкатегории (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    await state.update_data(subcategory_name=subcategory_name)
    
    await message.answer(
        f"✅ <b>Название сохранено:</b> {subcategory_name}\n\n"
        "Теперь введите slug (идентификатор) для подкатегории:\n"
        "<i>Пример: movies, games, anime\n(только латинские буквы, цифры и дефисы, без пробелов)</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_subcategory_slug)

@dp.message(AdminStates.waiting_for_subcategory_slug)
async def add_subcategory_slug(message: Message, state: FSMContext):
    """Получение slug подкатегории"""
    slug = message.text.strip().lower()
    
    # Проверяем slug на корректность
    if not slug or len(slug) < 2:
        await message.answer("❌ <b>Slug слишком короткий</b>\n\nВведите slug (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    # Проверяем, что slug состоит только из латинских букв, цифр и дефисов
    if not re.match(r'^[a-z0-9\-]+$', slug):
        await message.answer(
            "❌ <b>Некорректный slug</b>\n\n"
            "Slug должен содержать только:\n"
            "• Латинские буквы (a-z)\n"
            "• Цифры (0-9)\n"
            "• Дефисы (-)\n"
            "<i>Пример: movies, video-games, anime-series</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    data = await state.get_data()
    category_slug = data.get('category_slug')
    category_name = data.get('category_name')
    type_ = data.get('type')
    subcategory_name = data.get('subcategory_name')
    
    # Проверяем, не существует ли уже подкатегории с таким slug в этой категории и типе
    subcategories = db.get_subcategories_by_category_and_type(category_slug, type_)
    for subcat in subcategories:
        if subcat['slug'] == slug:
            await message.answer(
                f"❌ <b>Подкатегория с slug '{slug}' уже существует в этой категории и типе!</b>\n\n"
                f"Текущее название: {subcat['name']}\n"
                "Введите другой slug:",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Добавляем подкатегорию в базу данных
    success = db.add_subcategory(category_slug, subcategory_name, slug, type_)
    
    type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
    
    if success:
        await message.answer(
            f"✅ <b>Подкатегория успешно добавлена!</b>\n\n"
            f"📚 <b>Название:</b> {subcategory_name}\n"
            f"🔗 <b>Slug:</b> {slug}\n"
            f"📂 <b>Категория:</b> {category_name}\n"
            f"📦 <b>Тип:</b> {type_names[type_]}\n\n"
            "Подкатегория теперь доступна для добавления товаров.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении подкатегории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command('editsubcategory'))
async def edit_subcategory_start(message: Message, state: FSMContext):
    """Начало редактирования подкатегории"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем все подкатегории
    subcategories = db.get_all_subcategories_with_info()
    
    if not subcategories:
        await message.answer("❌ <b>Нет подкатегорий для редактирования</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for subcat in subcategories:
        type_icon = "✅" if subcat['type'] == 'instock' else "📅"
        builder.button(
            text=f"{type_icon} {subcat['category_name']} - {subcat['name']}",
            callback_data=f"editsubcat_{subcat['id']}"
        )
    
    builder.adjust(1)
    
    await message.answer(
        "📚 <b>Редактирование подкатегории</b>\n\n"
        "Выберите подкатегорию для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_edit_subcategory)

@dp.callback_query(F.data.startswith('editsubcat_'), AdminStates.waiting_for_edit_subcategory)
async def edit_subcategory_select(callback: CallbackQuery, state: FSMContext):
    """Выбор подкатегории для редактирования"""
    subcategory_id = int(callback.data.replace('editsubcat_', ''))
    
    # Получаем информацию о подкатегории
    subcategory = db.get_subcategory(subcategory_id)
    
    if not subcategory:
        await callback.answer("Подкатегория не найдена", show_alert=True)
        return
    
    await state.update_data(
        subcategory_id=subcategory_id,
        subcategory_data=subcategory
    )
    
    type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Изменить название", callback_data="editsubcat_name")
    builder.button(text="🔗 Изменить slug", callback_data="editsubcat_slug")
    builder.button(text="📦 Изменить тип", callback_data="editsubcat_type")
    builder.button(text="❌ Отмена", callback_data="editsubcat_cancel")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📚 <b>Редактирование подкатегории</b>\n\n"
        f"<b>Текущее название:</b> {subcategory['name']}\n"
        f"<b>Текущий slug:</b> {subcategory['slug']}\n"
        f"<b>Тип:</b> {type_names[subcategory['type']]}\n"
        f"<b>Категория:</b> {subcategory['category_slug']}\n\n"
        "Что вы хотите изменить?",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'editsubcat_name', AdminStates.waiting_for_edit_subcategory)
async def edit_subcategory_name_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения названия подкатегории"""
    await state.set_state(AdminStates.waiting_for_edit_subcategory_field)
    await state.update_data(edit_field='name')
    
    await callback.message.edit_text(
        "📝 <b>Изменение названия подкатегории</b>\n\n"
        "Введите новое название подкатегории:",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == 'editsubcat_slug', AdminStates.waiting_for_edit_subcategory)
async def edit_subcategory_slug_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения slug подкатегории"""
    await state.set_state(AdminStates.waiting_for_edit_subcategory_field)
    await state.update_data(edit_field='slug')
    
    await callback.message.edit_text(
        "🔗 <b>Изменение slug подкатегории</b>\n\n"
        "Введите новый slug (идентификатор) для подкатегории:\n"
        "<i>Пример: movies, games, anime\n(только латинские буквы, цифры и дефисы, без пробелов)</i>",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == 'editsubcat_type', AdminStates.waiting_for_edit_subcategory)
async def edit_subcategory_type_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения типа подкатегории"""
    await state.set_state(AdminStates.waiting_for_edit_subcategory_field)
    await state.update_data(edit_field='type')
    
    await callback.message.edit_text(
        "📦 <b>Изменение типа подкатегории</b>\n\n"
        "Выберите новый тип подкатегории:\n"
        "• <code>instock</code> - ✅ В наличии\n"
        "• <code>preorder</code> - 📅 Предзаказ\n\n"
        "Введите новый тип:",
        parse_mode=ParseMode.HTML
    )

@dp.message(AdminStates.waiting_for_edit_subcategory_field)
async def edit_subcategory_process(message: Message, state: FSMContext):
    """Обработка изменения подкатегории"""
    new_value = message.text.strip()
    data = await state.get_data()
    subcategory_id = data.get('subcategory_id')
    edit_field = data.get('edit_field')
    subcategory_data = data.get('subcategory_data')
    
    if not new_value:
        await message.answer("❌ <b>Значение не может быть пустым</b>", parse_mode=ParseMode.HTML)
        return
    
    # Валидация в зависимости от поля
    if edit_field == 'slug':
        # Проверяем slug на корректность
        if not re.match(r'^[a-z0-9\-]+$', new_value.lower()):
            await message.answer(
                "❌ <b>Некорректный slug</b>\n\n"
                "Slug должен содержать только латинские буквы, цифры и дефисы.",
                parse_mode=ParseMode.HTML
            )
            return
    
    elif edit_field == 'type':
        if new_value.lower() not in ['instock', 'preorder']:
            await message.answer(
                "❌ <b>Некорректный тип</b>\n\n"
                "Допустимые значения: <code>instock</code> или <code>preorder</code>",
                parse_mode=ParseMode.HTML
            )
            return
        new_value = new_value.lower()
    
    # Обновляем подкатегорию
    if edit_field == 'name':
        success = db.update_subcategory(subcategory_id, new_name=new_value)
    elif edit_field == 'slug':
        success = db.update_subcategory(subcategory_id, new_slug=new_value)
    elif edit_field == 'type':
        success = db.update_subcategory(subcategory_id, new_type=new_value)
    else:
        success = False
    
    type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
    field_names = {'name': 'Название', 'slug': 'Slug', 'type': 'Тип'}
    
    if success:
        await message.answer(
            f"✅ <b>{field_names[edit_field]} подкатегории успешно изменено!</b>\n\n"
            f"📚 <b>Старое значение:</b> {subcategory_data[edit_field] if edit_field != 'type' else type_names[subcategory_data[edit_field]]}\n"
            f"📚 <b>Новое значение:</b> {new_value if edit_field != 'type' else type_names[new_value]}",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при изменении подкатегории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.callback_query(F.data == 'editsubcat_cancel', AdminStates.waiting_for_edit_subcategory)
async def edit_subcategory_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования подкатегории"""
    await callback.message.edit_text(
        "❌ <b>Редактирование подкатегории отменено</b>",
        parse_mode=ParseMode.HTML
    )
    
    await state.clear()

@dp.message(Command('delsubcategory'))
async def delete_subcategory_start(message: Message, state: FSMContext):
    """Начало удаления подкатегории"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем все подкатегории
    subcategories = db.get_all_subcategories_with_info()
    
    if not subcategories:
        await message.answer("❌ <b>Нет подкатегорий для удаления</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for subcat in subcategories:
        type_icon = "✅" if subcat['type'] == 'instock' else "📅"
        builder.button(
            text=f"{type_icon} {subcat['category_name']} - {subcat['name']}",
            callback_data=f"delsubcat_{subcat['id']}"
        )
    
    builder.adjust(1)
    
    await message.answer(
        "🗑️ <b>Удаление подкатегории</b>\n\n"
        "<b>⚠️ Внимание:</b> При удалении подкатегории товары в ней останутся, но потеряют связь с подкатегорией.\n\n"
        "Выберите подкатегорию для удаления:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_delete_subcategory)

@dp.callback_query(F.data.startswith('delsubcat_'), AdminStates.waiting_for_delete_subcategory)
async def delete_subcategory_process(callback: CallbackQuery, state: FSMContext):
    """Удаление подкатегории"""
    subcategory_id = int(callback.data.replace('delsubcat_', ''))
    
    # Получаем информацию о подкатегории
    subcategory = db.get_subcategory(subcategory_id)
    
    if not subcategory:
        await callback.answer("Подкатегория не найдена", show_alert=True)
        return
    
    # Удаляем подкатегорию
    success = db.delete_subcategory(subcategory_id)
    
    if success:
        await callback.message.edit_text(
            f"✅ <b>Подкатегория успешно удалена!</b>\n\n"
            f"📚 <b>Удалена подкатегория:</b> {subcategory['name']}\n"
            f"🔗 <b>Slug:</b> {subcategory['slug']}\n"
            f"📂 <b>Категория:</b> {subcategory['category_slug']}\n"
            f"📦 <b>Тип:</b> {'✅ В наличии' if subcategory['type'] == 'instock' else '📅 Предзаказ'}\n\n"
            f"<i>Товары в этой подкатегории остались в базе, но потеряли связь с подкатегорией.</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при удалении подкатегории</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

# ==================== АДМИН КОМАНДЫ - УПРАВЛЕНИЕ ТОВАРАМИ ====================

@dp.message(Command('addproduct'))
async def add_product_start(message: Message, state: FSMContext):
    """Начало добавления товара"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer("❌ <b>Нет категорий. Сначала добавьте категорию!</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for slug, name in categories.items():
        builder.button(text=name, callback_data=f"addprod_cat_{slug}")
    
    builder.adjust(1)
    
    await message.answer(
        "📦 <b>Добавление нового товара</b>\n\n"
        "Выберите категорию товара:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_product_category)

@dp.callback_query(F.data.startswith('addprod_cat_'), AdminStates.waiting_for_product_category)
async def add_product_select_category(callback: CallbackQuery, state: FSMContext):
    """Выбор категории для товара"""
    category_slug = callback.data.replace('addprod_cat_', '')
    categories = db.get_categories()
    
    if category_slug not in categories:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    await state.update_data(category_slug=category_slug, category_name=categories[category_slug])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ В наличии", callback_data="addprod_type_instock")
    builder.button(text="📅 Предзаказ", callback_data="addprod_type_preorder")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📦 <b>Добавление товара</b>\n\n"
        f"<b>Категория:</b> {categories[category_slug]}\n\n"
        "Выберите тип товара:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_product_type)

@dp.callback_query(F.data.startswith('addprod_type_'), AdminStates.waiting_for_product_type)
async def add_product_select_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа товара"""
    type_ = callback.data.replace('addprod_type_', '')
    type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
    
    if type_ not in type_names:
        await callback.answer("Некорректный тип", show_alert=True)
        return
    
    data = await state.get_data()
    category_slug = data.get('category_slug')
    
    await state.update_data(type=type_)
    
    # Получаем подкатегории для выбранной категории и типа
    subcategories = db.get_subcategories_by_category_and_type(category_slug, type_)
    
    builder = InlineKeyboardBuilder()
    
    if subcategories:
        for subcat in subcategories:
            builder.button(text=subcat['name'], callback_data=f"addprod_subcat_{subcat['slug']}")
        builder.button(text="🚫 Без подкатегории", callback_data="addprod_nosubcat")
    else:
        builder.button(text="🚫 Нет подкатегорий", callback_data="addprod_nosubcat")
    
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📦 <b>Добавление товара</b>\n\n"
        f"<b>Тип:</b> {type_names[type_]}\n\n"
        "Выберите подкатегорию (если есть):",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('addprod_subcat_'), AdminStates.waiting_for_product_type)
async def add_product_select_subcategory(callback: CallbackQuery, state: FSMContext):
    """Выбор подкатегории для товара"""
    subcategory_slug = callback.data.replace('addprod_subcat_', '')
    await state.update_data(subcategory_slug=subcategory_slug)
    
    data = await state.get_data()
    category_slug = data.get('category_slug')
    type_ = data.get('type')
    
    # Получаем название подкатегории
    subcategories = db.get_subcategories_by_category_and_type(category_slug, type_)
    subcategory_name = None
    for subcat in subcategories:
        if subcat['slug'] == subcategory_slug:
            subcategory_name = subcat['name']
            break
    
    if subcategory_name:
        await state.update_data(subcategory_name=subcategory_name)
        await callback.message.edit_text(
            f"📦 <b>Добавление товара</b>\n\n"
            f"<b>Подкатегория:</b> {subcategory_name}\n\n"
            "Введите название товара:",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "📦 <b>Добавление товара</b>\n\n"
            "Введите название товара:",
            parse_mode=ParseMode.HTML
        )
    
    await state.set_state(AdminStates.waiting_for_product_name)

@dp.callback_query(F.data == 'addprod_nosubcat', AdminStates.waiting_for_product_type)
async def add_product_no_subcategory(callback: CallbackQuery, state: FSMContext):
    """Товар без подкатегории"""
    await state.update_data(subcategory_slug=None, subcategory_name=None)
    
    await callback.message.edit_text(
        "📦 <b>Добавление товара</b>\n\n"
        "Введите название товара:",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_product_name)

@dp.message(AdminStates.waiting_for_product_name)
async def add_product_name(message: Message, state: FSMContext):
    """Получение названия товара"""
    product_name = message.text.strip()
    
    if not product_name or len(product_name) < 2:
        await message.answer("❌ <b>Название слишком короткое</b>\n\nВведите название товара (минимум 2 символа).", parse_mode=ParseMode.HTML)
        return
    
    await state.update_data(product_name=product_name)
    
    await message.answer(
        f"✅ <b>Название сохранено:</b> {product_name}\n\n"
        "Теперь введите цену товара:\n"
        "<i>Пример: 3300 ₽, 1350 ₽, 3000 руб.</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_product_price)

@dp.message(AdminStates.waiting_for_product_price)
async def add_product_price(message: Message, state: FSMContext):
    """Получение цены товара"""
    price = message.text.strip()
    
    if not price:
        await message.answer("❌ <b>Цена не может быть пустой</b>\n\nВведите цену товара.", parse_mode=ParseMode.HTML)
        return
    
    await state.update_data(price=price)
    
    await message.answer(
        f"✅ <b>Цена сохранена:</b> {price}\n\n"
        "Теперь введите описание товара:\n"
        "<i>Можно написать подробное описание или нажать /skip чтобы пропустить</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_product_description)

@dp.message(AdminStates.waiting_for_product_description)
async def add_product_description(message: Message, state: FSMContext):
    """Получение описания товара"""
    if message.text == '/skip':
        description = None
    else:
        description = message.text.strip()
    
    await state.update_data(description=description)
    
    await message.answer(
        f"✅ <b>Описание сохранено</b>\n\n"
        "Теперь отправьте фото товара:\n"
        "<i>Отправьте одно или несколько фото, или нажмите /skip чтобы пропустить</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminStates.waiting_for_product_photos)

@dp.message(AdminStates.waiting_for_product_photos)
async def add_product_photos(message: Message, state: FSMContext):
    """Получение фото товара"""
    # Сначала проверяем команду /done
    if message.text and message.text.strip() == '/done':
        data = await state.get_data()
        photo_urls = data.get('photo_urls', [])
        
        await message.answer(
            f"✅ <b>Загрузка фото завершена!</b>\n"
            f"📸 Всего загружено фото: {len(photo_urls)}\n\n"
            "Теперь введите теги для поиска товара (через запятую):\n"
            "<i>Пример: funko, хоррор, фильм, пятница 13, джейсон\nИли нажмите /skip чтобы пропустить</i>",
            parse_mode=ParseMode.HTML
        )
        
        await state.set_state(AdminStates.waiting_for_product_tags)
        return
    
    # Затем проверяем команду /skip
    if message.text and message.text.strip() == '/skip':
        photo_urls = []
        await state.update_data(photo_urls=photo_urls)
        
        await message.answer(
            "✅ <b>Фото пропущены</b>\n\n"
            "Теперь введите теги для поиска товара (через запятую):\n"
            "<i>Пример: funko, хоррор, фильм, пятница 13, джейсон\nИли нажмите /skip чтобы пропустить</i>",
            parse_mode=ParseMode.HTML
        )
        
        await state.set_state(AdminStates.waiting_for_product_tags)
        return
    
    # Если это фото, а не текст
    if message.photo:
        try:
            photo = message.photo[-1]
            file_id = photo.file_id
            
            # Создаем папку для сохранения фото если её нет
            os.makedirs('img', exist_ok=True)
            
            # Получаем файл через message.bot
            file = await message.bot.get_file(file_id)
            file_path = file.file_path
            
            # Генерируем имя файла
            import uuid
            filename = f"{uuid.uuid4().hex}.jpg"
            save_path = f"img/{filename}"
            
            # Скачиваем файл
            await message.bot.download_file(file_path, save_path)
            
            # Получаем текущие фото из состояния
            data = await state.get_data()
            current_photo_urls = data.get('photo_urls', [])
            current_photo_urls.append(save_path)
            
            await state.update_data(photo_urls=current_photo_urls)
            
            await message.answer(
                f"✅ <b>Фото сохранено:</b> {filename}\n"
                f"📸 Загружено фото: {len(current_photo_urls)}\n\n"
                "Можете отправить ещё фото или нажмите /done чтобы закончить",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"Error saving photo: {e}")
            await message.answer(
                "❌ <b>Ошибка при сохранении фото</b>\n\n"
                "Попробуйте отправить фото еще раз или нажмите /skip чтобы пропустить",
                parse_mode=ParseMode.HTML
            )
    else:
        # Если это текст (не команда /done или /skip)
        await message.answer(
            "❌ <b>Пожалуйста, отправьте фото</b>\n\n"
            "Отправьте фото товара или нажмите:\n"
            "• /done - завершить загрузку фото\n"
            "• /skip - пропустить фото",
            parse_mode=ParseMode.HTML
        )



@dp.message(AdminStates.waiting_for_product_tags)
async def add_product_tags(message: Message, state: FSMContext):
    """Получение тегов товара"""
    if message.text == '/skip':
        tags = []
    else:
        tags = [tag.strip() for tag in message.text.split(',') if tag.strip()]
    
    # Получаем все данные
    data = await state.get_data()
    
    category_slug = data.get('category_slug')
    type_ = data.get('type')
    subcategory_slug = data.get('subcategory_slug')
    product_name = data.get('product_name')
    price = data.get('price')
    description = data.get('description')
    photo_urls = data.get('photo_urls', [])  # Получаем список фото
    
    # Добавляем товар в базу данных
    success = db.add_product(
        category_slug=category_slug,
        type_=type_,
        subcategory_slug=subcategory_slug,
        name=product_name,
        price=price,
        description=description,
        photo_urls=photo_urls,  # Передаем список фото
        tags=tags
    )
    
    if success:
        type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
        category_name = db.get_category_name(category_slug) or category_slug
        
        response = f"✅ <b>Товар успешно добавлен!</b>\n\n"
        response += f"🏷️ <b>Название:</b> {product_name}\n"
        response += f"💰 <b>Цена:</b> {price}\n"
        response += f"📂 <b>Категория:</b> {category_name}\n"
        response += f"📦 <b>Тип:</b> {type_names[type_]}\n"
        
        if subcategory_slug:
            response += f"📚 <b>Подкатегория:</b> {data.get('subcategory_name', subcategory_slug)}\n"
        
        if description:
            response += f"📝 <b>Описание:</b> {description[:100]}...\n" if len(description) > 100 else f"📝 <b>Описание:</b> {description}\n"
        
        if photo_urls:
            response += f"📸 <b>Фото:</b> {len(photo_urls)} шт.\n"
        
        if tags:
            response += f"🏷️ <b>Теги:</b> {', '.join(tags[:5])}"
            if len(tags) > 5:
                response += f"... (всего {len(tags)})"
        
        await message.answer(response, parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command('editproduct'))
async def edit_product_start(message: Message, state: FSMContext):
    """Начало редактирования товара"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем товары для выбора
    products = db.get_products_for_selection()
    
    if not products:
        await message.answer("❌ <b>Нет товаров для редактирования</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for product in products:
        product_name = product['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        
        # ИСПРАВЛЕНО: используем новый префикс edit_product_ вместо editprod_
        builder.button(
            text=f"{product_name} - {product['price']}",
            callback_data=f"edit_product_{product['id']}"
        )
    
    builder.adjust(1)
    
    await message.answer(
        "📝 <b>Редактирование товара</b>\n\n"
        "Выберите товар для редактирования:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_edit_product)

@dp.callback_query(F.data.startswith('edit_product_'), AdminStates.waiting_for_edit_product)
async def edit_product_select(callback: CallbackQuery, state: FSMContext):
    """Выбор товара для редактирования"""
    try:
        product_id = int(callback.data.replace('edit_product_', ''))
        
        # Получаем информацию о товаре
        product = db.get_product(product_id)
        
        if not product:
            await callback.answer("Товар не найдена", show_alert=True)
            return
        
        await state.update_data(
            product_id=product_id,
            product_data=product
        )
        
        type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
        
        # Получаем количество фото
        photo_count = len(product.get('photo_urls', []))
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Изменить название", callback_data="edit_field_name")
        builder.button(text="💰 Изменить цену", callback_data="edit_field_price")
        builder.button(text="📝 Изменить описание", callback_data="edit_field_description")
        builder.button(text="📂 Изменить категорию", callback_data="edit_field_category")
        builder.button(text="📦 Изменить тип", callback_data="edit_field_type")
        builder.button(text="📚 Изменить подкатегорию", callback_data="edit_field_subcategory")
        builder.button(text="🏷️ Изменить теги", callback_data="edit_field_tags")
        # ДОБАВЛЯЕМ КНОПКУ ДЛЯ УПРАВЛЕНИЯ ФОТО
        builder.button(text=f"🖼️ Управление фото ({photo_count})", callback_data="edit_field_photos")
        builder.button(text="❌ Отмена", callback_data="edit_field_cancel")
        builder.adjust(1)
        
        await callback.message.edit_text(
            f"📝 <b>Редактирование товара</b>\n\n"
            f"<b>Товар:</b> {product['name']}\n"
            f"<b>Цена:</b> {product['price']}\n"
            f"<b>Категория:</b> {product['category_slug']}\n"
            f"<b>Тип:</b> {type_names[product['type']]}\n"
            f"<b>Подкатегория:</b> {product['subcategory_slug'] or 'Нет'}\n"
            f"<b>Фото:</b> {photo_count} шт.\n"
            f"<b>Теги:</b> {', '.join(product.get('tags', [])[:3]) if product.get('tags') else 'Нет'}\n\n"
            "Что вы хотите изменить?",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Error in edit_product_select: {e}")
        await callback.answer("Ошибка при выборе товара", show_alert=True)

@dp.callback_query(F.data == 'edit_field_photos', AdminStates.waiting_for_edit_product)
async def edit_product_photos_menu(callback: CallbackQuery, state: FSMContext):
    """Меню управления фотографиями товара"""
    data = await state.get_data()
    product_data = data.get('product_data')
    product_id = data.get('product_id')
    
    # Получаем текущие фото
    photo_urls = product_data.get('photo_urls', [])
    photo_count = len(photo_urls)
    
    await state.set_state(AdminStates.waiting_for_edit_product_photos_menu)
    
    # Используем новую функцию для отображения меню
    await update_photos_menu_message(callback.message, product_data)

@dp.callback_query(F.data == 'back_to_edit_menu')
async def back_to_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Вернуться в меню редактирования товара"""
    try:
        # Очищаем состояние меню фото
        await state.set_state(AdminStates.waiting_for_edit_product)
        
        # Получаем данные из состояния
        data = await state.get_data()
        product_id = data.get('product_id')
        
        if not product_id:
            await callback.answer("Ошибка: товар не найден", show_alert=True)
            return
        
        # Обновляем данные товара из базы
        product = db.get_product(product_id)
        if not product:
            await callback.answer("Товар не найден в базе", show_alert=True)
            return
        
        await state.update_data(product_data=product)
        
        type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
        
        # Получаем количество фото
        photo_count = len(product.get('photo_urls', []))
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Изменить название", callback_data="edit_field_name")
        builder.button(text="💰 Изменить цену", callback_data="edit_field_price")
        builder.button(text="📝 Изменить описание", callback_data="edit_field_description")
        builder.button(text="📂 Изменить категорию", callback_data="edit_field_category")
        builder.button(text="📦 Изменить тип", callback_data="edit_field_type")
        builder.button(text="📚 Изменить подкатегорию", callback_data="edit_field_subcategory")
        builder.button(text="🏷️ Изменить теги", callback_data="edit_field_tags")
        builder.button(text=f"🖼️ Управление фото ({photo_count})", callback_data="edit_field_photos")
        builder.button(text="❌ Отмена", callback_data="edit_field_cancel")
        builder.adjust(1)
        
        await callback.message.edit_text(
            f"📝 <b>Редактирование товара</b>\n\n"
            f"<b>Товар:</b> {product['name']}\n"
            f"<b>Цена:</b> {product['price']}\n"
            f"<b>Категория:</b> {product['category_slug']}\n"
            f"<b>Тип:</b> {type_names[product['type']]}\n"
            f"<b>Подкатегория:</b> {product['subcategory_slug'] or 'Нет'}\n"
            f"<b>Фото:</b> {photo_count} шт.\n"
            f"<b>Теги:</b> {', '.join(product.get('tags', [])[:3]) if product.get('tags') else 'Нет'}\n\n"
            "Что вы хотите изменить?",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Error in back_to_edit_menu: {e}")
        await callback.answer("Ошибка при возврате к редактированию", show_alert=True)

@dp.callback_query(F.data.startswith('view_photo_'), AdminStates.waiting_for_edit_product_photos_menu)
async def view_product_photo(callback: CallbackQuery, state: FSMContext):
    """Просмотр конкретного фото товара"""
    photo_index = int(callback.data.replace('view_photo_', ''))
    
    data = await state.get_data()
    product_data = data.get('product_data')
    product_id = data.get('product_id')
    
    photo_urls = product_data.get('photo_urls', [])
    
    if photo_index < 0 or photo_index >= len(photo_urls):
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    photo_path = photo_urls[photo_index]
    
    try:
        # Проверяем существование файла
        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            await callback.message.answer_photo(
                photo=photo,
                caption=f"📷 <b>Фото {photo_index + 1} из {len(photo_urls)}</b>\n"
                       f"Товар: {product_data['name']}",
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.answer(f"Файл не найден: {photo_path}", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка при загрузке фото: {e}", show_alert=True)

@dp.callback_query(F.data == 'add_more_photos', AdminStates.waiting_for_edit_product_photos_menu)
async def add_product_photos_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления новых фото"""
    await state.set_state(AdminStates.waiting_for_add_product_photos)
    
    await callback.message.edit_text(
        "➕ <b>Добавление новых фото к товару</b>\n\n"
        "Отправьте одно или несколько фото.\n"
        "Когда закончите, нажмите /done\n\n"
        "<i>Поддерживаются только фото в формате JPG/PNG</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(AdminStates.waiting_for_add_product_photos)
async def add_product_photos_process(message: Message, state: FSMContext, bot: Bot):
    """Обработка добавления новых фото"""
    data = await state.get_data()
    product_id = data.get('product_id')
    product_data = data.get('product_data')
    
    # Проверяем команды
    if message.text and message.text.strip() == '/done':
        # Завершаем добавление фото
        new_photo_urls = data.get('new_photo_urls', [])
        
        if new_photo_urls:
            # Обновляем товар с новыми фото
            current_photos = product_data.get('photo_urls', [])
            updated_photos = current_photos + new_photo_urls
            
            success = db.update_product(product_id, photo_urls=updated_photos)
            
            if success:
                await message.answer(
                    f"✅ <b>Добавлено {len(new_photo_urls)} новых фото!</b>\n\n"
                    f"📸 Теперь у товара {len(updated_photos)} фото.\n\n"
                    "Возвращаемся в меню управления фото...",
                    parse_mode=ParseMode.HTML
                )
                
                # Обновляем данные товара в состоянии
                updated_product = db.get_product(product_id)
                await state.update_data(product_data=updated_product, new_photo_urls=[])
                
                # Возвращаемся в меню управления фото
                # Вместо создания искусственного CallbackQuery, просто отправляем сообщение с кнопками
                await show_photos_menu_after_add(message, product_id, updated_product)
            else:
                await message.answer(
                    "❌ <b>Ошибка при сохранении фото</b>\n\n"
                    "Попробуйте снова или обратитесь к разработчику.",
                    parse_mode=ParseMode.HTML
                )
        else:
            await message.answer(
                "📸 <b>Не добавлено ни одного нового фото</b>\n\n"
                "Возвращаемся в меню управления фото...",
                parse_mode=ParseMode.HTML
            )
            
            # Возвращаемся в меню управления фото
            await show_photos_menu_after_add(message, product_id, product_data)
        
        return
    
    # Обработка фото
    if message.photo:
        try:
            photo = message.photo[-1]
            file_id = photo.file_id
            
            # Создаем папку для фото если её нет
            os.makedirs('img', exist_ok=True)
            
            # Получаем файл
            file = await bot.get_file(file_id)
            file_path = file.file_path
            
            # Генерируем уникальное имя файла
            import uuid
            filename = f"{uuid.uuid4().hex}.jpg"
            save_path = f"img/{filename}"
            
            # Скачиваем файл
            await bot.download_file(file_path, save_path)
            
            # Получаем текущие новые фото из состояния
            current_new_photos = data.get('new_photo_urls', [])
            current_new_photos.append(save_path)
            
            await state.update_data(new_photo_urls=current_new_photos)
            
            await message.answer(
                f"✅ <b>Фото сохранено!</b>\n"
                f"📸 Загружено новых фото: {len(current_new_photos)}\n\n"
                "Можете отправить ещё фото или нажмите /done чтобы закончить",
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            print(f"Error saving photo: {e}")
            await message.answer(
                "❌ <b>Ошибка при сохранении фото</b>\n\n"
                "Попробуйте отправить фото еще раз.",
                parse_mode=ParseMode.HTML
            )
    else:
        # Если это не фото и не команда
        await message.answer(
            "❌ <b>Пожалуйста, отправьте фото</b>\n\n"
            "Отправьте фото товара или нажмите /done чтобы закончить",
            parse_mode=ParseMode.HTML
        )

async def show_photos_menu_after_add(message: Message, product_id: int, product_data: dict):
    """Показать меню управления фото после добавления новых фото"""
    photo_urls = product_data.get('photo_urls', [])
    photo_count = len(photo_urls)
    
    builder = InlineKeyboardBuilder()
    
    # Показываем текущие фото с номерами
    if photo_urls:
        for i, photo_url in enumerate(photo_urls, 1):
            builder.button(text=f"📷 Фото {i}", callback_data=f"view_photo_{i-1}")
        
        # Кнопки для управления
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
        builder.button(text="🗑️ Удалить фото", callback_data="delete_photo_menu")
        builder.button(text="🔄 Заменить фото", callback_data="replace_photo_menu")
        builder.button(text="📋 Удалить все фото", callback_data="delete_all_photos")
    else:
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
    
    builder.button(text="⬅️ Назад к редактированию", callback_data="back_to_edit_menu")
    builder.adjust(1)
    
    await message.answer(
        f"🖼️ <b>Управление фотографиями товара</b>\n\n"
        f"<b>Товар:</b> {product_data['name']}\n"
        f"<b>Текущее количество фото:</b> {photo_count}\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'delete_photo_menu', AdminStates.waiting_for_edit_product_photos_menu)
async def delete_product_photo_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора фото для удаления"""
    data = await state.get_data()
    product_data = data.get('product_data')
    
    photo_urls = product_data.get('photo_urls', [])
    
    if not photo_urls:
        await callback.answer("Нет фото для удаления", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_delete_product_photo)
    
    builder = InlineKeyboardBuilder()
    
    for i, photo_url in enumerate(photo_urls, 1):
        builder.button(text=f"🗑️ Удалить фото {i}", callback_data=f"delete_photo_{i-1}")
    
    builder.button(text="⬅️ Назад", callback_data="back_to_photos_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🗑️ <b>Удаление фото товара</b>\n\n"
        f"<b>Товар:</b> {product_data['name']}\n"
        f"<b>Всего фото:</b> {len(photo_urls)}\n\n"
        "Выберите фото для удаления:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith('delete_photo_'), AdminStates.waiting_for_delete_product_photo)
async def delete_product_photo_process(callback: CallbackQuery, state: FSMContext):
    """Удаление конкретного фото"""
    photo_index = int(callback.data.replace('delete_photo_', ''))
    
    data = await state.get_data()
    product_id = data.get('product_id')
    product_data = data.get('product_data')
    
    photo_urls = product_data.get('photo_urls', [])
    
    if photo_index < 0 or photo_index >= len(photo_urls):
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    # Удаляем фото из списка
    photo_to_delete = photo_urls[photo_index]
    updated_photo_urls = photo_urls.copy()
    updated_photo_urls.pop(photo_index)
    
    # Обновляем товар в базе
    success = db.update_product(product_id, photo_urls=updated_photo_urls)
    
    if success:
        # Пытаемся удалить файл с диска
        try:
            if os.path.exists(photo_to_delete):
                os.remove(photo_to_delete)
        except Exception as e:
            print(f"Error deleting file {photo_to_delete}: {e}")
        
        await callback.answer(f"Фото {photo_index + 1} удалено!", show_alert=True)
        
        # Обновляем данные товара в состоянии
        updated_product = db.get_product(product_id)
        await state.update_data(product_data=updated_product)
        
        # Обновляем текущее сообщение с новым меню
        await update_photos_menu_message(callback.message, updated_product)
    else:
        await callback.answer("Ошибка при удалении фото", show_alert=True)

async def update_photos_menu_message(message: Message, product_data: dict):
    """Обновить сообщение с меню управления фото"""
    photo_urls = product_data.get('photo_urls', [])
    photo_count = len(photo_urls)
    
    builder = InlineKeyboardBuilder()
    
    # Показываем текущие фото с номерами
    if photo_urls:
        for i, photo_url in enumerate(photo_urls, 1):
            builder.button(text=f"📷 Фото {i}", callback_data=f"view_photo_{i-1}")
        
        # Кнопки для управления
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
        builder.button(text="🗑️ Удалить фото", callback_data="delete_photo_menu")
        builder.button(text="🔄 Заменить фото", callback_data="replace_photo_menu")
        builder.button(text="📋 Удалить все фото", callback_data="delete_all_photos")
    else:
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
    
    builder.button(text="⬅️ Назад к редактированию", callback_data="back_to_edit_menu")
    builder.adjust(1)
    
    try:
        await message.edit_text(
            f"🖼️ <b>Управление фотографиями товара</b>\n\n"
            f"<b>Товар:</b> {product_data['name']}\n"
            f"<b>Текущее количество фото:</b> {photo_count}\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    except Exception:
        # Если не удалось редактировать сообщение, отправляем новое
        await message.answer(
            f"🖼️ <b>Управление фотографиями товара</b>\n\n"
            f"<b>Товар:</b> {product_data['name']}\n"
            f"<b>Текущее количество фото:</b> {photo_count}\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )

@dp.callback_query(F.data == 'delete_all_photos', AdminStates.waiting_for_edit_product_photos_menu)
async def delete_all_product_photos(callback: CallbackQuery, state: FSMContext):
    """Удаление всех фото товара"""
    data = await state.get_data()
    product_id = data.get('product_id')
    product_data = data.get('product_data')
    
    photo_urls = product_data.get('photo_urls', [])
    
    if not photo_urls:
        await callback.answer("Нет фото для удаления", show_alert=True)
        return
    
    # Создаем кнопки подтверждения
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить все фото", callback_data="confirm_delete_all_photos")
    builder.button(text="❌ Нет, отменить", callback_data="cancel_delete_all_photos")
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        f"Вы собираетесь удалить <b>ВСЕ {len(photo_urls)} ФОТО</b> товара:\n"
        f"<b>{product_data['name']}</b>\n\n"
        f"Это действие нельзя отменить!\n\n"
        f"Вы уверены?",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == 'confirm_delete_all_photos')
async def confirm_delete_all_photos(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления всех фото"""
    data = await state.get_data()
    product_id = data.get('product_id')
    product_data = data.get('product_data')
    
    photo_urls = product_data.get('photo_urls', [])
    
    # Обновляем товар (удаляем все фото)
    success = db.update_product(product_id, photo_urls=[])
    
    if success:
        # Пытаемся удалить файлы с диска
        for photo_url in photo_urls:
            try:
                if os.path.exists(photo_url):
                    os.remove(photo_url)
            except Exception as e:
                print(f"Error deleting file {photo_url}: {e}")
        
        await callback.answer("Все фото удалены!", show_alert=True)
        
        # Обновляем данные товара в состоянии
        updated_product = db.get_product(product_id)
        await state.update_data(product_data=updated_product)
        
        # Обновляем меню
        await update_photos_menu_message(callback.message, updated_product)
    else:
        await callback.answer("Ошибка при удалении фото", show_alert=True)

@dp.callback_query(F.data == 'cancel_delete_all_photos')
async def cancel_delete_all_photos(callback: CallbackQuery, state: FSMContext):
    """Отмена удаления всех фото"""
    data = await state.get_data()
    product_data = data.get('product_data')
    
    await update_photos_menu_message(callback.message, product_data)    

@dp.callback_query(F.data == 'back_to_photos_menu', AdminStates.waiting_for_delete_product_photo)
async def back_to_photos_menu_from_delete(callback: CallbackQuery, state: FSMContext):
    """Вернуться в меню управления фото"""
    data = await state.get_data()
    product_data = data.get('product_data')
    
    await state.set_state(AdminStates.waiting_for_edit_product_photos_menu)
    await update_photos_menu_message(callback.message, product_data)

@dp.callback_query(F.data.startswith('edit_field_'), AdminStates.waiting_for_edit_product)
async def edit_product_field_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения поля товара"""
    field = callback.data.replace('edit_field_', '')
    
    if field == 'cancel':
        await callback.message.edit_text(
            "❌ <b>Редактирование товара отменено</b>",
            parse_mode=ParseMode.HTML
        )
        await state.clear()
        return
    
    field_names = {
        'name': 'название',
        'price': 'цену',
        'description': 'описание',
        'category': 'категорию',
        'type': 'тип',
        'subcategory': 'подкатегорию',
        'tags': 'теги',
        'photos': 'фотографии'
    }
    
    if field in field_names:
        await state.set_state(AdminStates.waiting_for_edit_product_field)
        await state.update_data(edit_field=field)
        
        if field == 'category':
            # Показываем список категорий
            categories = db.get_categories()
            builder = InlineKeyboardBuilder()
            
            for slug, name in categories.items():
                builder.button(text=name, callback_data=f"editprod_cat_{slug}")
            
            builder.adjust(1)
            
            await callback.message.edit_text(
                f"📂 <b>Изменение категории товара</b>\n\n"
                "Выберите новую категорию:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        elif field == 'type':
            # Показываем выбор типа
            builder = InlineKeyboardBuilder()
            builder.button(text="✅ В наличии", callback_data="editprod_type_instock")
            builder.button(text="📅 Предзаказ", callback_data="editprod_type_preorder")
            builder.adjust(1)
            
            await callback.message.edit_text(
                f"📦 <b>Изменение типа товара</b>\n\n"
                "Выберите новый тип:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        elif field == 'subcategory':
            data = await state.get_data()
            product_data = data.get('product_data')
            
            # Получаем подкатегории для текущей категории и типа
            subcategories = db.get_subcategories_by_category_and_type(
                product_data['category_slug'], 
                product_data['type']
            )
            
            builder = InlineKeyboardBuilder()
            
            if subcategories:
                for subcat in subcategories:
                    builder.button(text=subcat['name'], callback_data=f"editprod_subcat_{subcat['slug']}")
                builder.button(text="🚫 Без подкатегории", callback_data="editprod_nosubcat")
            else:
                builder.button(text="🚫 Нет подкатегорий", callback_data="editprod_nosubcat")
            
            builder.adjust(1)
            
            await callback.message.edit_text(
                f"📚 <b>Изменение подкатегории товара</b>\n\n"
                "Выберите новую подкатегорию:",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            return
        
        elif field == 'photos':
            # Переходим в меню управления фото
            await edit_product_photos_menu(callback, state)
            return
        
       
        
        else:
            # Для остальных полей запрашиваем текстовый ввод
            prompt_texts = {
                'name': "Введите новое название товара:",
                'price': "Введите новую цену товара:",
                'description': "Введите новое описание товара (или /skip чтобы удалить):",
                'tags': "Введите новые теги через запятую (или /skip чтобы удалить):"
            }
            
            await callback.message.edit_text(
                f"📝 <b>Изменение {field_names[field]} товара</b>\n\n"
                f"{prompt_texts[field]}",
                parse_mode=ParseMode.HTML
            )

@dp.callback_query(F.data.startswith('editprod_cat_'), AdminStates.waiting_for_edit_product_field)
async def edit_product_category_select(callback: CallbackQuery, state: FSMContext):
    """Выбор новой категории для товара"""
    new_category_slug = callback.data.replace('editprod_cat_', '')
    
    data = await state.get_data()
    product_id = data.get('product_id')
    
    # Обновляем товар
    success = db.update_product(product_id, category_slug=new_category_slug)
    
    if success:
        category_name = db.get_category_name(new_category_slug) or new_category_slug
        await callback.message.edit_text(
            f"✅ <b>Категория товара успешно изменена!</b>\n\n"
            f"📂 <b>Новая категория:</b> {category_name}",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при изменении категории товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith('editprod_type_'), AdminStates.waiting_for_edit_product_field)
async def edit_product_type_select(callback: CallbackQuery, state: FSMContext):
    """Выбор нового типа для товара"""
    new_type = callback.data.replace('editprod_type_', '')
    
    data = await state.get_data()
    product_id = data.get('product_id')
    
    # Обновляем товар
    success = db.update_product(product_id, type=new_type)
    
    if success:
        type_names = {'preorder': '📅 Предзаказ', 'instock': '✅ В наличии'}
        await callback.message.edit_text(
            f"✅ <b>Тип товара успешно изменен!</b>\n\n"
            f"📦 <b>Новый тип:</b> {type_names[new_type]}",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при изменении типа товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith('editprod_subcat_'), AdminStates.waiting_for_edit_product_field)
async def edit_product_subcategory_select(callback: CallbackQuery, state: FSMContext):
    """Выбор новой подкатегории для товара"""
    new_subcategory_slug = callback.data.replace('editprod_subcat_', '')
    
    data = await state.get_data()
    product_id = data.get('product_id')
    product_data = data.get('product_data')
    
    # Обновляем товар
    success = db.update_product(product_id, subcategory_slug=new_subcategory_slug)
    
    if success:
        # Получаем название подкатегории
        subcategories = db.get_subcategories_by_category_and_type(
            product_data['category_slug'], 
            product_data['type']
        )
        subcategory_name = None
        for subcat in subcategories:
            if subcat['slug'] == new_subcategory_slug:
                subcategory_name = subcat['name']
                break
        
        await callback.message.edit_text(
            f"✅ <b>Подкатегория товара успешно изменена!</b>\n\n"
            f"📚 <b>Новая подкатегория:</b> {subcategory_name or new_subcategory_slug}",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при изменении подкатегории товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.callback_query(F.data == 'editprod_nosubcat', AdminStates.waiting_for_edit_product_field)
async def edit_product_no_subcategory(callback: CallbackQuery, state: FSMContext):
    """Удаление подкатегории у товара"""
    data = await state.get_data()
    product_id = data.get('product_id')
    
    # Обновляем товар
    success = db.update_product(product_id, subcategory_slug=None)
    
    if success:
        await callback.message.edit_text(
            f"✅ <b>Подкатегория товара успешно удалена!</b>\n\n"
            f"📚 Теперь товар без подкатегории",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при удалении подкатегории товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(AdminStates.waiting_for_edit_product_field)
async def edit_product_field_process(message: Message, state: FSMContext):
    """Обработка изменения поля товара"""
    new_value = message.text.strip()
    data = await state.get_data()
    product_id = data.get('product_id')
    edit_field = data.get('edit_field')
    product_data = data.get('product_data')
    
    if edit_field == 'description' and message.text == '/skip':
        new_value = None
    elif edit_field == 'tags' and message.text == '/skip':
        new_value = []
    elif edit_field == 'tags':
        new_value = [tag.strip() for tag in message.text.split(',') if tag.strip()]
    
    # Обновляем товар
    if edit_field == 'name':
        success = db.update_product(product_id, name=new_value)
    elif edit_field == 'price':
        success = db.update_product(product_id, price=new_value)
    elif edit_field == 'description':
        success = db.update_product(product_id, description=new_value)
    elif edit_field == 'tags':
        success = db.update_product(product_id, tags=new_value)
    else:
        success = False
    
    field_names = {
        'name': 'Название',
        'price': 'Цена',
        'description': 'Описание',
        'tags': 'Теги'
    }
    
    if success:
        if edit_field == 'description' and new_value is None:
            await message.answer(
                f"✅ <b>Описание товара успешно удалено!</b>",
                parse_mode=ParseMode.HTML
            )
        elif edit_field == 'tags' and not new_value:
            await message.answer(
                f"✅ <b>Теги товара успешно удалены!</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            display_value = new_value
            if edit_field == 'tags':
                display_value = ', '.join(new_value[:5])
                if len(new_value) > 5:
                    display_value += f"... (всего {len(new_value)})"
            
            await message.answer(
                f"✅ <b>{field_names[edit_field]} товара успешно изменено!</b>\n\n"
                f"📝 <b>Новое значение:</b> {display_value}",
                parse_mode=ParseMode.HTML
            )
    else:
        await message.answer(
            "❌ <b>Ошибка при изменении товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

@dp.message(Command('delproduct'))
async def delete_product_start(message: Message, state: FSMContext):
    """Начало удаления товара"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Получаем товары для выбора
    products = db.get_products_for_selection()
    
    if not products:
        await message.answer("❌ <b>Нет товаров для удаления</b>", parse_mode=ParseMode.HTML)
        return
    
    builder = InlineKeyboardBuilder()
    
    for product in products:
        product_name = product['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        
        builder.button(
            text=f"{product_name} - {product['price']}",
            callback_data=f"delprod_{product['id']}"
        )
    
    builder.adjust(1)
    
    await message.answer(
        "🗑️ <b>Удаление товара</b>\n\n"
        "<b>⚠️ Внимание:</b> Товар будет удален без возможности восстановления!\n\n"
        "Выберите товар для удаления:",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(AdminStates.waiting_for_delete_product)

@dp.callback_query(F.data.startswith('delprod_'), AdminStates.waiting_for_delete_product)
async def delete_product_process(callback: CallbackQuery, state: FSMContext):
    """Удаление товара"""
    product_id = int(callback.data.replace('delprod_', ''))
    
    # Получаем информацию о товаре
    product = db.get_product(product_id)
    
    if not product:
        await callback.answer("Товар не найдена", show_alert=True)
        return
    
    # Удаляем товар
    success = db.delete_product(product_id)
    
    if success:
        await callback.message.edit_text(
            f"✅ <b>Товар успешно удален!</b>\n\n"
            f"🗑️ <b>Удален товар:</b> {product['name']}\n"
            f"💰 <b>Цена:</b> {product['price']}\n"
            f"📂 <b>Категория:</b> {product['category_slug']}\n\n"
            f"<i>Товар удален без возможности восстановления.</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Ошибка при удалении товара</b>\n\n"
            "Попробуйте снова или обратитесь к разработчику.",
            parse_mode=ParseMode.HTML
        )
    
    await state.clear()

# ==================== АДМИН КОМАНДЫ - ПОИСК ====================

@dp.message(Command('search'))
async def admin_search_products(message: Message):
    """Поиск товаров (только для админов)"""
    # Проверяем права
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("🚫 <b>Доступ запрещен</b>\n\nЭта команда доступна только администраторам.", parse_mode=ParseMode.HTML)
        return
    
    # Пытаемся получить поисковый запрос из команды
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) >= 2:
        search_query = command_parts[1]
        # Ищем товары
        products = db.search_products(search_query)
        
        if not products:
            await message.answer(f"❌ <b>По запросу \"{search_query}\" ничего не найдено</b>", parse_mode=ParseMode.HTML)
            return
        
        response = f"🔍 <b>Результаты поиска для админа:</b>\n"
        response += f"Запрос: <code>{search_query}</code>\n"
        response += f"Найдено: {len(products)} товаров\n\n"
        
        for product in products[:20]:
            type_icon = "📅" if product['type'] == 'preorder' else "✅"
            response += f"• {type_icon} <b>{product['name']}</b> - {product['price']}\n"
            response += f"  ID: {product['id']}, Категория: {product['category_slug']}\n"
            response += f"  Тип: {product['type']}, Подкатегория: {product.get('subcategory_slug', 'Нет')}\n\n"
        
        if len(products) > 20:
            response += f"... и ещё {len(products) - 20} товаров"
        
        await message.answer(response, parse_mode=ParseMode.HTML)
    else:
        # Если запрос не указан, запрашиваем его
        await message.answer(
            "🔍 <b>Поиск товаров (админ)</b>\n\n"
            "Введите поисковый запрос:\n"
            "<i>Пример: /search танк</i>",
            parse_mode=ParseMode.HTML
        )
async def update_photos_menu_message(message: Message, product_data: dict):
    """Обновить сообщение с меню управления фото"""
    photo_urls = product_data.get('photo_urls', [])
    photo_count = len(photo_urls)
    
    builder = InlineKeyboardBuilder()
    
    # Показываем текущие фото с номерами
    if photo_urls:
        for i, photo_url in enumerate(photo_urls, 1):
            builder.button(text=f"📷 Фото {i}", callback_data=f"view_photo_{i-1}")
        
        # Кнопки для управления
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
        builder.button(text="🗑️ Удалить фото", callback_data="delete_photo_menu")
        builder.button(text="🔄 Заменить фото", callback_data="replace_photo_menu")
        builder.button(text="📋 Удалить все фото", callback_data="delete_all_photos")
    else:
        builder.button(text="➕ Добавить фото", callback_data="add_more_photos")
    
    builder.button(text="⬅️ Назад к редактированию", callback_data="back_to_edit_menu")
    builder.adjust(1)
    
    try:
        await message.edit_text(
            f"🖼️ <b>Управление фотографиями товара</b>\n\n"
            f"<b>Товар:</b> {product_data['name']}\n"
            f"<b>Текущее количество фото:</b> {photo_count}\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    except Exception:
        # Если не удалось редактировать сообщение, отправляем новое
        await message.answer(
            f"🖼️ <b>Управление фотографиями товара</b>\n\n"
            f"<b>Товар:</b> {product_data['name']}\n"
            f"<b>Текущее количество фото:</b> {photo_count}\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )        

# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

async def main() -> None:
    """Основная функция запуска бота"""
     # Создаем папку для фото если её нет
    os.makedirs('img', exist_ok=True)
    print(f"📁 Папка для фото: {os.path.abspath('img')}")

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    categories = db.get_categories()
    
    bot_info = await bot.get_me()
    print(f"\n{'='*60}")
    print(f"🤖 БОТ ASIAHAPPY ЗАПУЩЕН")
    print(f"{'='*60}")
    print(f"👤 Имя бота: {bot_info.full_name}")
    print(f"🔗 Username: @{bot_info.username}")
    print(f"🆔 ID бота: {bot_info.id}")
    print(f"{'-'*60}")
    print(f"👑 Админы: {', '.join(ADMINS)}")
    print(f"{'-'*60}")
    
    if categories:
        print(f"📂 Категорий в базе: {len(categories)}")
        
        # Получаем количество подкатегорий
        subcategories_count = len(db.get_all_subcategories())
        print(f"📚 Подкатегорий в базе: {subcategories_count}")
        
        total_products = db.get_all_products_count()
        print(f"📦 Товаров в базе: {total_products}")
    else:
        print("⚠️ База данных пуста или недоступна!")
        print("💡 Запустите: python init_db.py")
    
    print(f"{'-'*60}")
    print("📋 ДОСТУПНЫЕ КОМАНДЫ:")
    print("• /start - Главное меню")
    print("• /catalog - Каталог товаров")
    print("• /help - Помощь по боту")
    print("• /admin - Админ-панель (только для админов)")
    print(f"{'-'*60}")
    print(f"👨‍💼 Менеджер: @AsiaHappyManager")
    print(f"{'='*60}")
    print("\n🚀 Бот готов к работе! Ожидание сообщений...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"\n❌ Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()
        db.close()
        print("\n🛑 Бот остановлен. Соединения закрыты.")

if __name__ == "__main__":
    # Создаем папку для фото если её нет
    os.makedirs('img', exist_ok=True)
    
    # Настройка стандартного логирования aiogram
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )
    
    print("\n" + "="*60)
    print("🚀 ЗАПУСК БОТА ASIAHAPPY С АДМИНКОЙ И ПОДКАТЕГОРИЯМИ")
    print("="*60)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Бот AsiaHappy остановлен пользователем")
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")