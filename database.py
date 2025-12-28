import sqlite3
import os
import json
from typing import List, Dict, Optional, Union
from datetime import datetime

class Database:
    def __init__(self, db_name: str = 'products.db'):
        """
        Инициализация базы данных с автоматическим обновлением схемы
        
        Args:
            db_name: Имя файла базы данных
        """
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._current_version = 3  # Текущая версия схемы БД
        
        # Проверяем и обновляем базу данных при необходимости
        self._check_and_upgrade_database()
    
    def _check_and_upgrade_database(self) -> None:
        """
        Проверка версии базы данных и автоматическое обновление
        """
        try:
            # Создаем таблицу для хранения версии БД, если её нет
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS db_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Получаем текущую версию БД
            self.cursor.execute('SELECT value FROM db_info WHERE key = "version"')
            result = self.cursor.fetchone()
            current_db_version = int(result[0]) if result else 1
            
            print(f"📊 Версия базы данных: {current_db_version}")
            print(f"📊 Текущая версия схемы: {self._current_version}")
            
            # Если версия БД устарела, выполняем обновление
            if current_db_version < self._current_version:
                print(f"🔄 Обновление базы данных с версии {current_db_version} до {self._current_version}...")
                self._upgrade_database(current_db_version)
                print("✅ База данных успешно обновлена!")
            
            # Если это новая БД, устанавливаем текущую версию
            if not result:
                self.cursor.execute('INSERT INTO db_info (key, value) VALUES ("version", ?)', (str(self._current_version),))
                self.conn.commit()
            
            # Создаем/обновляем таблицы
            self._create_tables()
            
        except Exception as e:
            print(f"❌ Ошибка при проверке/обновлении базы данных: {e}")
            # В случае ошибки, просто создаем таблицы заново
            self._create_tables()
    
    def _upgrade_database(self, from_version: int) -> None:
        """
        Обновление базы данных с указанной версии до текущей
        
        Args:
            from_version: Версия базы данных для обновления
        """
        try:
            # Последовательно применяем обновления
            for version in range(from_version + 1, self._current_version + 1):
                print(f"  Применение обновления до версии {version}...")
                
                if version == 2:
                    self._upgrade_to_version_2()
                elif version == 3:
                    self._upgrade_to_version_3()
                # Добавьте здесь другие обновления для будущих версий
                
                # Обновляем версию в БД
                self.cursor.execute('''
                    INSERT OR REPLACE INTO db_info (key, value) 
                    VALUES ("version", ?)
                ''', (str(version),))
                self.conn.commit()
                
                print(f"  ✅ Обновление до версии {version} завершено")
        
        except Exception as e:
            print(f"❌ Ошибка при обновлении базы данных: {e}")
            self.conn.rollback()
            raise
    
    def _upgrade_to_version_2(self) -> None:
        """
        Обновление до версии 2: добавление тегов для товаров
        """
        # Добавляем поле tags в таблицу products
        try:
            self.cursor.execute('ALTER TABLE products ADD COLUMN tags TEXT DEFAULT "[]"')
        except sqlite3.OperationalError:
            # Поле уже существует
            pass
        
        # Обновляем существующие товары, добавляя пустые теги
        self.cursor.execute('UPDATE products SET tags = "[]" WHERE tags IS NULL')
    
    def _upgrade_to_version_3(self) -> None:
        """
        Обновление до версии 3: улучшенные индексы и оптимизация
        """
        # Создаем улучшенные индексы
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_search ON products(name, tags)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity ON users(last_seen)')
        
        # Добавляем поле для хранения времени последнего обновления товара
        try:
            self.cursor.execute('ALTER TABLE products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        except sqlite3.OperationalError:
            # Поле уже существует
            pass
    
    def _create_tables(self) -> None:
        """Создание таблиц в базе данных"""
        try:
            # Таблица категорий
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица подкатегорий
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS subcategories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    type TEXT NOT NULL,  -- 'preorder' или 'instock'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category_slug, slug, type),
                    FOREIGN KEY (category_slug) REFERENCES categories(slug)
                )
            ''')
            
            # Таблица товаров
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_slug TEXT NOT NULL,
                    type TEXT NOT NULL,
                    subcategory_slug TEXT,
                    name TEXT NOT NULL,
                    price TEXT NOT NULL,
                    description TEXT,
                    photo_urls TEXT,
                    tags TEXT DEFAULT "[]",  -- JSON список тегов для поиска
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_slug) REFERENCES categories(slug),
                    FOREIGN KEY (subcategory_slug) REFERENCES subcategories(slug)
                )
            ''')
            
            # Таблица пользователей (для статистики и банов)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_banned BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    product_clicks INTEGER DEFAULT 0,
                    total_clicks INTEGER DEFAULT 0
                )
            ''')
            
            # Таблица статистики по товарам
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_stats (
                    product_id INTEGER,
                    clicks INTEGER DEFAULT 0,
                    last_click TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            ''')
            
            # Таблица активных сессий
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_sessions (
                    user_id INTEGER,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Индексы для быстрого поиска
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_category_slug ON products(category_slug)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_type ON products(type)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_subcategory_slug ON products(subcategory_slug)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_category_type ON products(category_slug, type)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_tags ON products(tags)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_banned ON users(is_banned)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_clicks ON product_stats(clicks)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_subcat_type ON subcategories(category_slug, type)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_search ON products(name, tags)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity ON users(last_seen)')
            
            self.conn.commit()
            print("✅ Таблицы базы данных успешно созданы/проверены")
        except Exception as e:
            print(f"❌ Ошибка при создании таблиц: {e}")
            raise
        
    
    def add_category(self, name: str, slug: str) -> bool:
        """
        Добавление категории
        
        Args:
            name: Название категории
            slug: Уникальный идентификатор категории
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            self.cursor.execute(
                'INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?)',
                (name, slug)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error adding category {slug}: {e}")
            return False
    
    def update_category(self, old_slug: str, new_name: Optional[str] = None, new_slug: Optional[str] = None) -> bool:
        """
        Обновление категории
        
        Args:
            old_slug: Старый slug категории
            new_name: Новое название (опционально)
            new_slug: Новый slug (опционально)
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            updates = []
            values = []
            
            if new_name:
                updates.append("name = ?")
                values.append(new_name)
            
            if new_slug:
                updates.append("slug = ?")
                values.append(new_slug)
            
            if not updates:
                return False
            
            values.append(old_slug)
            query = f"UPDATE categories SET {', '.join(updates)} WHERE slug = ?"
            
            # Если меняем slug, нужно обновить ссылки в товарах и подкатегориях
            if new_slug:
                self.cursor.execute('UPDATE products SET category_slug = ? WHERE category_slug = ?', (new_slug, old_slug))
                self.cursor.execute('UPDATE subcategories SET category_slug = ? WHERE category_slug = ?', (new_slug, old_slug))
            
            self.cursor.execute(query, values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating category {old_slug}: {e}")
            return False
    
    def delete_category(self, slug: str) -> bool:
        """
        Удаление категории и всех товаров в ней
        
        Args:
            slug: Slug категории
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Сначала удаляем все подкатегории в этой категории
            self.cursor.execute('DELETE FROM subcategories WHERE category_slug = ?', (slug,))
            
            # Получаем ID всех товаров в этой категории
            self.cursor.execute('SELECT id FROM products WHERE category_slug = ?', (slug,))
            product_ids = [row[0] for row in self.cursor.fetchall()]
            
            # Удаляем статистику товаров
            for product_id in product_ids:
                self.cursor.execute('DELETE FROM product_stats WHERE product_id = ?', (product_id,))
            
            # Удаляем все товары в этой категории
            self.cursor.execute('DELETE FROM products WHERE category_slug = ?', (slug,))
            
            # Удаляем саму категорию
            self.cursor.execute('DELETE FROM categories WHERE slug = ?', (slug,))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting category {slug}: {e}")
            return False
    
    def add_subcategory(self, category_slug: str, name: str, slug: str, type_: str) -> bool:
        """
        Добавление подкатегории
        
        Args:
            category_slug: Slug родительской категории
            name: Название подкатегории
            slug: Уникальный идентификатор подкатегории
            type_: Тип ('preorder' или 'instock')
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            self.cursor.execute(
                '''INSERT OR IGNORE INTO subcategories (category_slug, name, slug, type) 
                   VALUES (?, ?, ?, ?)''',
                (category_slug, name, slug, type_)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error adding subcategory {slug}: {e}")
            return False
    
    def update_subcategory(self, subcategory_id: int, new_name: Optional[str] = None, 
                          new_slug: Optional[str] = None, new_type: Optional[str] = None) -> bool:
        """
        Обновление подкатегории
        
        Args:
            subcategory_id: ID подкатегории
            new_name: Новое название (опционально)
            new_slug: Новый slug (опционально)
            new_type: Новый тип (опционально)
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            updates = []
            values = []
            
            if new_name:
                updates.append("name = ?")
                values.append(new_name)
            
            if new_slug:
                updates.append("slug = ?")
                values.append(new_slug)
            
            if new_type:
                updates.append("type = ?")
                values.append(new_type)
            
            if not updates:
                return False
            
            values.append(subcategory_id)
            query = f"UPDATE subcategories SET {', '.join(updates)} WHERE id = ?"
            
            self.cursor.execute(query, values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating subcategory {subcategory_id}: {e}")
            return False
    
    def delete_subcategory(self, subcategory_id: int) -> bool:
        """
        Удаление подкатегории
        
        Args:
            subcategory_id: ID подкатегории
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Удаляем подкатегорию
            self.cursor.execute('DELETE FROM subcategories WHERE id = ?', (subcategory_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting subcategory {subcategory_id}: {e}")
            return False
    
    def get_subcategories_by_category_and_type(self, category_slug: str, type_: str) -> List[Dict]:
        """
        Получение подкатегорий по категории и типу
        
        Args:
            category_slug: Slug категории
            type_: Тип ('preorder' или 'instock')
            
        Returns:
            List[Dict]: Список подкатегорий
        """
        try:
            self.cursor.execute('''
                SELECT id, name, slug 
                FROM subcategories 
                WHERE category_slug = ? AND type = ?
                ORDER BY name
            ''', (category_slug, type_))
            
            rows = self.cursor.fetchall()
            return [{'id': row[0], 'name': row[1], 'slug': row[2]} for row in rows]
        except Exception as e:
            print(f"Error getting subcategories for {category_slug}/{type_}: {e}")
            return []
    
    def get_subcategory(self, subcategory_id: int) -> Optional[Dict]:
        """
        Получение подкатегории по ID
        
        Args:
            subcategory_id: ID подкатегории
            
        Returns:
            Dict: Информация о подкатегории или None
        """
        try:
            self.cursor.execute('''
                SELECT id, category_slug, name, slug, type 
                FROM subcategories 
                WHERE id = ?
            ''', (subcategory_id,))
            
            row = self.cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'category_slug': row[1],
                    'name': row[2],
                    'slug': row[3],
                    'type': row[4]
                }
            return None
        except Exception as e:
            print(f"Error getting subcategory {subcategory_id}: {e}")
            return None
    
    def get_all_subcategories(self) -> List[Dict]:
        """
        Получение всех подкатегорий
        
        Returns:
            List[Dict]: Список всех подкатегорий
        """
        try:
            self.cursor.execute('''
                SELECT s.id, s.name, s.slug, s.type, c.name as category_name
                FROM subcategories s
                JOIN categories c ON s.category_slug = c.slug
                ORDER BY c.name, s.type, s.name
            ''')
            
            rows = self.cursor.fetchall()
            return [{
                'id': row[0],
                'name': row[1],
                'slug': row[2],
                'type': row[3],
                'category_name': row[4]
            } for row in rows]
        except Exception as e:
            print(f"Error getting all subcategories: {e}")
            return []
    
    def add_product(self, category_slug: str, type_: str, subcategory_slug: Optional[str], 
                   name: str, price: str, description: Optional[str] = None, 
                   photo_urls: Optional[Union[str, List[str]]] = None,
                   tags: Optional[List[str]] = None) -> bool:
        """
        Добавление товара
        
        Args:
            category_slug: Идентификатор категории
            type_: Тип товара (preorder/instock)
            subcategory_slug: Идентификатор подкатегории (опционально)
            name: Название товара
            price: Цена товара
            description: Описание товара
            photo_urls: Путь к фото или список путей
            tags: Список тегов для поиска
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Обрабатываем фото
            processed_photo_urls = self._process_photo_urls(photo_urls)
            
            # Обрабатываем теги
            processed_tags = json.dumps(tags, ensure_ascii=False) if tags else '[]'
            
            self.cursor.execute('''
                INSERT INTO products (category_slug, type, subcategory_slug, name, price, description, photo_urls, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (category_slug, type_, subcategory_slug, name, price, description, processed_photo_urls, processed_tags))
            
            # Создаем запись в статистике
            product_id = self.cursor.lastrowid
            self.cursor.execute('INSERT OR IGNORE INTO product_stats (product_id, clicks) VALUES (?, 0)', (product_id,))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error adding product {name}: {e}")
            return False
    
    def _process_photo_urls(self, photo_urls: Optional[Union[str, List[str]]]) -> str:
        """
        Обработка путей к фото
        
        Args:
            photo_urls: Путь или список путей к фото
            
        Returns:
            str: JSON строка с путями к фото
        """
        if not photo_urls:
            return json.dumps(["img/no_photo.webp"], ensure_ascii=False)
        
        if isinstance(photo_urls, str):
            # Если строка, создаем список
            photo_list = [url.strip() for url in photo_urls.split(',') if url.strip()]
        elif isinstance(photo_urls, list):
            photo_list = photo_urls
        else:
            photo_list = []
        
        # Если список пуст, добавляем заглушку
        if not photo_list:
            photo_list = ["img/no_photo.webp"]
        
        # Убеждаемся, что пути корректны
        processed_list = []
        for url in photo_list:
            url = url.strip()
            if url.startswith('/'):
                url = url[1:]  # Убираем начальный слэш
            if not url.startswith('img/'):
                url = f"img/{url}"
            processed_list.append(url)
        
        return json.dumps(processed_list, ensure_ascii=False)
    
    def get_categories(self) -> Dict[str, str]:
        """
        Получение всех категорий
        
        Returns:
            Dict[str, str]: Словарь {slug: name}
        """
        try:
            self.cursor.execute('SELECT slug, name FROM categories ORDER BY name')
            categories = self.cursor.fetchall()
            return dict(categories) if categories else {}
        except Exception as e:
            print(f"Error getting categories: {e}")
            return {}
    
    def get_category_name(self, slug: str) -> Optional[str]:
        """
        Получение названия категории по slug
        
        Args:
            slug: Идентификатор категории
            
        Returns:
            str: Название категории или None
        """
        try:
            self.cursor.execute('SELECT name FROM categories WHERE slug = ?', (slug,))
            result = self.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting category name for {slug}: {e}")
            return None
    
    def get_products_by_category_and_type(self, category_slug: str, type_: str, subcategory_slug: Optional[str] = None) -> List[Dict]:
        """
        Получение товаров по категории, типу и подкатегории
        
        Args:
            category_slug: Идентификатор категории
            type_: Тип товара (preorder/instock)
            subcategory_slug: Идентификатор подкатегории (опционально)
            
        Returns:
            List[Dict]: Список товаров
        """
        try:
            if subcategory_slug:
                self.cursor.execute('''
                    SELECT id, name, price, description, photo_urls, type, created_at, tags, subcategory_slug
                    FROM products 
                    WHERE category_slug = ? AND type = ? AND subcategory_slug = ?
                    ORDER BY created_at DESC, id
                ''', (category_slug, type_, subcategory_slug))
            else:
                self.cursor.execute('''
                    SELECT id, name, price, description, photo_urls, type, created_at, tags, subcategory_slug
                    FROM products 
                    WHERE category_slug = ? AND type = ?
                    ORDER BY created_at DESC, id
                ''', (category_slug, type_))
            
            rows = self.cursor.fetchall()
            products = []
            for row in rows:
                # Парсим JSON с фото
                photo_urls_json = row[4] or '[]'
                try:
                    photo_urls = json.loads(photo_urls_json)
                except:
                    photo_urls = []
                
                # Проверяем существование фото
                available_photos = []
                for photo_url in photo_urls:
                    if self._check_photo_exists(photo_url):
                        available_photos.append(photo_url)
                
                # Парсим теги
                tags_json = row[7] or '[]'
                try:
                    tags = json.loads(tags_json)
                except:
                    tags = []
                
                products.append({
                    'id': row[0],
                    'name': row[1],
                    'price': row[2],
                    'description': row[3] or 'Нет описания',
                    'photo_urls': available_photos,
                    'type': row[5],
                    'created_at': row[6],
                    'tags': tags,
                    'subcategory_slug': row[8]
                })
            return products
        except Exception as e:
            print(f"Error getting products for {category_slug}/{type_}: {e}")
            return []
    
    def _check_photo_exists(self, photo_url: str) -> bool:
        """
        Проверка существования файла с фото
        
        Args:
            photo_url: Путь к фото
            
        Returns:
            bool: True если файл существует
        """
        if not photo_url:
            return False
        
        # Проверяем разные варианты пути
        paths_to_check = [
            photo_url,
            f"./{photo_url}" if not photo_url.startswith('./') else None,
            photo_url.lstrip('/') if photo_url.startswith('/') else None,
            f"img/{photo_url}" if not photo_url.startswith('img/') else None
        ]
        
        for path in paths_to_check:
            if path and os.path.exists(path):
                return True
        
        return False
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        """
        Получение товара по ID
        
        Args:
            product_id: ID товара
            
        Returns:
            Dict: Информация о товаре или None
        """
        try:
            self.cursor.execute('''
                SELECT name, price, description, photo_urls, type, category_slug, subcategory_slug, created_at, tags, id
                FROM products 
                WHERE id = ?
            ''', (product_id,))
            
            row = self.cursor.fetchone()
            if row:
                # Парсим JSON с фото
                photo_urls_json = row[3] or '[]'
                try:
                    photo_urls = json.loads(photo_urls_json)
                except:
                    photo_urls = []
                
                # Проверяем существование фото
                available_photos = []
                for photo_url in photo_urls:
                    if self._check_photo_exists(photo_url):
                        available_photos.append(photo_url)
                
                # Парсим теги
                tags_json = row[8] or '[]'
                try:
                    tags = json.loads(tags_json)
                except:
                    tags = []
                
                return {
                    'name': row[0],
                    'price': row[1],
                    'description': row[2] or 'Нет описания',
                    'photo_urls': available_photos,
                    'main_photo': available_photos[0] if available_photos else None,
                    'type': row[4],
                    'category_slug': row[5],
                    'subcategory_slug': row[6],
                    'created_at': row[7],
                    'tags': tags,
                    'id': row[9]
                }
            return None
        except Exception as e:
            print(f"Error getting product {product_id}: {e}")
            return None
    
    def search_products(self, search_query: str) -> List[Dict]:
        """
        Поиск товаров по ключевым словам
        
        Args:
            search_query: Поисковый запрос
            
        Returns:
            List[Dict]: Список найденных товаров
        """
        try:
            # Подготавливаем поисковый запрос
            search_terms = search_query.lower().split()
            if not search_terms:
                return []
            
            # Создаем условия поиска
            conditions = []
            params = []
            
            for term in search_terms:
                conditions.append('''
                    (LOWER(name) LIKE ? OR 
                     LOWER(description) LIKE ? OR
                     LOWER(tags) LIKE ?)
                ''')
                like_term = f'%{term}%'
                params.extend([like_term, like_term, like_term])
            
            where_clause = ' OR '.join(conditions) if len(conditions) > 1 else conditions[0]
            
            self.cursor.execute(f'''
                SELECT id, name, price, description, photo_urls, type, category_slug, subcategory_slug, tags
                FROM products 
                WHERE {where_clause}
                ORDER BY 
                    CASE 
                        WHEN LOWER(name) LIKE ? THEN 1
                        WHEN LOWER(description) LIKE ? THEN 2
                        ELSE 3
                    END,
                    name
            ''', params + [f'%{search_terms[0]}%', f'%{search_terms[0]}%'])
            
            rows = self.cursor.fetchall()
            products = []
            for row in rows:
                # Парсим JSON с фото
                photo_urls_json = row[4] or '[]'
                try:
                    photo_urls = json.loads(photo_urls_json)
                except:
                    photo_urls = []
                
                # Проверяем существование фото
                available_photos = []
                for photo_url in photo_urls:
                    if self._check_photo_exists(photo_url):
                        available_photos.append(photo_url)
                
                # Парсим теги
                tags_json = row[8] or '[]'
                try:
                    tags = json.loads(tags_json)
                except:
                    tags = []
                
                products.append({
                    'id': row[0],
                    'name': row[1],
                    'price': row[2],
                    'description': row[3] or 'Нет описания',
                    'photo_urls': available_photos,
                    'type': row[5],
                    'category_slug': row[6],
                    'subcategory_slug': row[7],
                    'tags': tags
                })
            return products
        except Exception as e:
            print(f"Error searching products: {e}")
            return []
    
    def get_product_by_name(self, name: str) -> Optional[Dict]:
        """
        Получение товара по названию
        
        Args:
            name: Название товара
            
        Returns:
            Dict: Информация о товаре или None
        """
        try:
            self.cursor.execute('''
                SELECT id, name, price, description, photo_urls, type, category_slug, subcategory_slug
                FROM products 
                WHERE name = ?
            ''', (name,))
            
            row = self.cursor.fetchone()
            if row:
                # Парсим JSON с фото
                photo_urls_json = row[4] or '[]'
                try:
                    photo_urls = json.loads(photo_urls_json)
                except:
                    photo_urls = []
                
                # Проверяем существование фото
                available_photos = []
                for photo_url in photo_urls:
                    if self._check_photo_exists(photo_url):
                        available_photos.append(photo_url)
                
                return {
                    'id': row[0],
                    'name': row[1],
                    'price': row[2],
                    'description': row[3] or 'Нет описания',
                    'photo_urls': available_photos,
                    'type': row[5],
                    'category_slug': row[6],
                    'subcategory_slug': row[7]
                }
            return None
        except Exception as e:
            print(f"Error getting product {name}: {e}")
            return None
    
    def get_all_products(self) -> List[Dict]:
        """
        Получение всех товаров
        
        Returns:
            List[Dict]: Список всех товаров
        """
        try:
            self.cursor.execute('''
                SELECT id, name, price, description, photo_urls, type, category_slug, subcategory_slug, tags, created_at
            FROM products 
            ORDER BY created_at DESC, category_slug, name
            ''')
            
            rows = self.cursor.fetchall()
            products = []
            for row in rows:
                # Парсим JSON с фото
                photo_urls_json = row[4] or '[]'
                try:
                    photo_urls = json.loads(photo_urls_json)
                except:
                    photo_urls = []
                
                # Проверяем существование фото
                available_photos = []
                for photo_url in photo_urls:
                    if self._check_photo_exists(photo_url):
                        available_photos.append(photo_url)
                
                # Парсим теги
                tags_json = row[8] or '[]'
                try:
                    tags = json.loads(tags_json)
                except:
                    tags = []
                
                products.append({
                'id': row[0],
                'name': row[1],
                'price': row[2],
                'description': row[3] or 'Нет описания',
                'photo_urls': available_photos,
                'type': row[5],
                'category_slug': row[6],
                'subcategory_slug': row[7],
                'tags': tags,
                'created_at': row[9]  # Добавляем дату создания
            })
            return products
        except Exception as e:
            print(f"Error getting all products: {e}")
            return []
        
    
    def update_product(self, product_id: int, **kwargs) -> bool:
        """
        Обновление информации о товаре
        
        Args:
            product_id: ID товара
            **kwargs: Поля для обновления
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            valid_fields = ['name', 'price', 'description', 'photo_urls', 'type', 'category_slug', 'subcategory_slug', 'tags']
            updates = []
            values = []
            
            for field, value in kwargs.items():
                if field in valid_fields:
                    if field == 'photo_urls':
                        value = self._process_photo_urls(value)
                    elif field == 'tags':
                        value = json.dumps(value, ensure_ascii=False) if value else '[]'
                    updates.append(f"{field} = ?")
                    values.append(value)
            
            if not updates:
                return False
            
            # Добавляем время обновления
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            values.append(product_id)
            query = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"
            
            self.cursor.execute(query, values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating product {product_id}: {e}")
            return False
    
    def delete_product(self, product_id: int) -> bool:
        """
        Удаление товара
        
        Args:
            product_id: ID товара
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Удаляем статистику товара
            self.cursor.execute('DELETE FROM product_stats WHERE product_id = ?', (product_id,))
            
            # Удаляем сам товар
            self.cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting product {product_id}: {e}")
            return False
    
    def get_product_count_by_category(self, category_slug: str, type_: Optional[str] = None) -> int:
        """
        Получение количества товаров в категории
        
        Args:
            category_slug: Идентификатор категории
            type_: Тип товара (preorder/instock) или None для всех
            
        Returns:
            int: Количество товаров
        """
        try:
            if type_:
                self.cursor.execute('''
                    SELECT COUNT(*) FROM products 
                    WHERE category_slug = ? AND type = ?
                ''', (category_slug, type_))
            else:
                self.cursor.execute('''
                    SELECT COUNT(*) FROM products 
                    WHERE category_slug = ?
                ''', (category_slug,))
            
            return self.cursor.fetchone()[0]
        except Exception as e:
            print(f"Error getting product count for {category_slug}: {e}")
            return 0
    
    def get_all_products_count(self) -> int:
        """
        Получение общего количества товаров
        
        Returns:
            int: Количество товаров
        """
        try:
            self.cursor.execute('SELECT COUNT(*) FROM products')
            return self.cursor.fetchone()[0]
        except Exception as e:
            print(f"Error getting products count: {e}")
            return 0
    
    # ==================== НОВЫЕ МЕТОДЫ ДЛЯ АДМИНКИ ====================
    
    def get_all_categories_with_info(self) -> List[Dict]:
        """
        Получение всех категорий с дополнительной информацией
        
        Returns:
            List[Dict]: Список категорий с ID и другими данными
        """
        try:
            self.cursor.execute('''
                SELECT id, slug, name, created_at, 
                       (SELECT COUNT(*) FROM products WHERE category_slug = categories.slug) as product_count
                FROM categories 
                ORDER BY name
            ''')
            
            rows = self.cursor.fetchall()
            return [{
                'id': row[0],
                'slug': row[1],
                'name': row[2],
                'created_at': row[3],
                'product_count': row[4]
            } for row in rows]
        except Exception as e:
            print(f"Error getting all categories with info: {e}")
            return []
    
    def get_subcategory_by_slug(self, category_slug: str, subcategory_slug: str, type_: str) -> Optional[Dict]:
        """
        Получение подкатегории по slug
        
        Args:
            category_slug: Slug категории
            subcategory_slug: Slug подкатегории
            type_: Тип подкатегории
            
        Returns:
            Dict: Информация о подкатегории или None
        """
        try:
            self.cursor.execute('''
                SELECT id, name, slug, type 
                FROM subcategories 
                WHERE category_slug = ? AND slug = ? AND type = ?
            ''', (category_slug, subcategory_slug, type_))
            
            row = self.cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'slug': row[2],
                    'type': row[3]
                }
            return None
        except Exception as e:
            print(f"Error getting subcategory {subcategory_slug}: {e}")
            return None
    
    def get_all_subcategories_with_info(self) -> List[Dict]:
        """
        Получение всех подкатегорий с информацией
        
        Returns:
            List[Dict]: Список подкатегорий
        """
        try:
            self.cursor.execute('''
                SELECT s.id, s.name, s.slug, s.type, s.category_slug, 
                       c.name as category_name,
                       (SELECT COUNT(*) FROM products WHERE subcategory_slug = s.slug AND type = s.type) as product_count
                FROM subcategories s
                JOIN categories c ON s.category_slug = c.slug
                ORDER BY c.name, s.type, s.name
            ''')
            
            rows = self.cursor.fetchall()
            return [{
                'id': row[0],
                'name': row[1],
                'slug': row[2],
                'type': row[3],
                'category_slug': row[4],
                'category_name': row[5],
                'product_count': row[6]
            } for row in rows]
        except Exception as e:
            print(f"Error getting all subcategories with info: {e}")
            return []
    
    def delete_subcategory_by_slug(self, category_slug: str, subcategory_slug: str, type_: str) -> bool:
        """
        Удаление подкатегории по slug
        
        Args:
            category_slug: Slug категории
            subcategory_slug: Slug подкатегории
            type_: Тип подкатегории
            
        Returns:
            bool: True если успешно
        """
        try:
            # Получаем ID подкатегории
            subcat = self.get_subcategory_by_slug(category_slug, subcategory_slug, type_)
            if not subcat:
                return False
            
            subcategory_id = subcat['id']
            
            # Удаляем подкатегорию
            self.cursor.execute('DELETE FROM subcategories WHERE id = ?', (subcategory_id,))
            
            # Обновляем товары, удаляя ссылку на подкатегорию
            self.cursor.execute('''
                UPDATE products 
                SET subcategory_slug = NULL 
                WHERE category_slug = ? AND subcategory_slug = ? AND type = ?
            ''', (category_slug, subcategory_slug, type_))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting subcategory {subcategory_slug}: {e}")
            return False
    
    def get_all_products_with_info(self) -> List[Dict]:
        """
        Получение всех товаров с полной информацией
        
        Returns:
            List[Dict]: Список товаров
        """
        try:
            self.cursor.execute('''
                SELECT p.id, p.name, p.price, p.type, 
                       p.category_slug, p.subcategory_slug,
                       c.name as category_name,
                       ps.clicks as view_count,
                       p.created_at
                FROM products p
                LEFT JOIN categories c ON p.category_slug = c.slug
                LEFT JOIN product_stats ps ON p.id = ps.product_id
                ORDER BY p.created_at DESC
            ''')
            
            rows = self.cursor.fetchall()
            return [{
                'id': row[0],
                'name': row[1],
                'price': row[2],
                'type': row[3],
                'category_slug': row[4],
                'subcategory_slug': row[5],
                'category_name': row[6],
                'view_count': row[7] or 0,
                'created_at': row[8]
            } for row in rows]
        except Exception as e:
            print(f"Error getting all products with info: {e}")
            return []
    
    def get_products_for_selection(self) -> List[Dict]:
        """
        Получение товаров для выбора (например, при удалении)
        
        Returns:
            List[Dict]: Список товаров
        """
        try:
            self.cursor.execute('''
                SELECT id, name, category_slug, price, type
                FROM products 
                ORDER BY category_slug, name
                LIMIT 100
            ''')
            
            rows = self.cursor.fetchall()
            return [{
                'id': row[0],
                'name': row[1],
                'category_slug': row[2],
                'price': row[3],
                'type': row[4]
            } for row in rows]
        except Exception as e:
            print(f"Error getting products for selection: {e}")
            return []
    
    def update_product_photos(self, product_id: int, photo_urls: List[str]) -> bool:
        """
        Обновление фото товара
        
        Args:
            product_id: ID товара
            photo_urls: Список путей к фото
            
        Returns:
            bool: True если успешно
        """
        try:
            processed_photo_urls = self._process_photo_urls(photo_urls)
            
            self.cursor.execute('''
                UPDATE products 
                SET photo_urls = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (processed_photo_urls, product_id))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating product photos {product_id}: {e}")
            return False
    
    # ==================== МЕТОДЫ ДЛЯ АДМИНКИ ====================
    
    def get_all_users_for_broadcast(self) -> List[Dict]:
        """
        Получение всех пользователей для рассылки
    
        Returns:
            List[Dict]: Список пользователей
        """
        try:
            self.cursor.execute('''
                SELECT user_id, username, first_name, last_name, is_banned
                FROM users 
                ORDER BY last_seen DESC
        ''')
        
            rows = self.cursor.fetchall()
            users = []
            for row in rows:
                users.append({
                    'user_id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'is_banned': row[4]
            })
            return users
        except Exception as e:
            print(f"Error getting users for broadcast: {e}")
            return []
        
    def mark_user_inactive(self, user_id: int) -> None:
        """
        Пометить пользователя как неактивного
        """
        try:
            self.cursor.execute('''
                 UPDATE users 
                 SET is_active = 0 
                 WHERE user_id = ?  
            ''', (user_id,))
        except Exception as e:
            print(f"Error marking user as inactive: {e}")    
    def get_active_users_24h(self) -> List[Dict]:
        """
        Получение активных пользователей за последние 24 часа
    
        Returns:
            List[Dict]: Список активных пользователей
        """
        try:
            self.cursor.execute('''
                SELECT user_id, username, first_name, last_name
                FROM users 
                WHERE last_seen >= datetime('now', '-1 day') 
                AND is_banned = 0
                ORDER BY last_seen DESC
            ''')
        
            rows = self.cursor.fetchall()
            users = []
            for row in rows:
                users.append({
                    'user_id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3]
                })
            return users
        except Exception as e:
            print(f"Error getting active users: {e}")
            return []        
    
    def register_user(self, user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]) -> None:
        """
        Регистрация/обновление пользователя
        
        Args:
            user_id: ID пользователя
            username: Имя пользователя
            first_name: Имя
            last_name: Фамилия
        """
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO users (id, username, first_name, last_name, last_seen)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, username, first_name, last_name))
            self.conn.commit()
        except Exception as e:
            print(f"Error registering user {user_id}: {e}")
    
    def update_user_activity(self, user_id: int) -> None:
        """
        Обновление активности пользователя
        
        Args:
            user_id: ID пользователя
        """
        try:
            # Обновляем время последней активности
            self.cursor.execute('''
                UPDATE users 
                SET last_seen = CURRENT_TIMESTAMP,
                    total_clicks = total_clicks + 1
                WHERE id = ?
            ''', (user_id,))
            
            # Добавляем/обновляем активную сессию
            self.cursor.execute('''
                INSERT OR REPLACE INTO active_sessions (user_id, last_activity)
                VALUES (?, CURRENT_TIMESTAMP)
            ''', (user_id,))
            
            self.conn.commit()
        except Exception as e:
            print(f"Error updating user activity {user_id}: {e}")
    
    def increment_product_clicks(self, user_id: int, product_id: int) -> None:
        """
        Увеличение счетчика кликов по товару
        
        Args:
            user_id: ID пользователя
            product_id: ID товара
        """
        try:
            # Увеличиваем счетчик кликов по товару
            self.cursor.execute('''
                INSERT OR REPLACE INTO product_stats (product_id, clicks, last_click)
                VALUES (?, COALESCE((SELECT clicks FROM product_stats WHERE product_id = ?), 0) + 1, CURRENT_TIMESTAMP)
            ''', (product_id, product_id))
            
            # Увеличиваем счетчик кликов пользователя
            self.cursor.execute('''
                UPDATE users 
                SET product_clicks = product_clicks + 1
                WHERE id = ?
            ''', (user_id,))
            
            self.conn.commit()
        except Exception as e:
            print(f"Error incrementing product clicks: {e}")
    
    def ban_user(self, username: str) -> bool:
        """
        Бан пользователя по username
        
        Args:
            username: Имя пользователя (с @ или без)
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Убираем @ если есть
            if username.startswith('@'):
                username = username[1:]
            
            self.cursor.execute('''
                UPDATE users 
                SET is_banned = 1 
                WHERE username = ?
            ''', (username,))
            
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Error banning user {username}: {e}")
            return False
    
    def unban_user(self, username: str) -> bool:
        """
        Разбан пользователя по username
        
        Args:
            username: Имя пользователя (с @ или без)
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Убираем @ если есть
            if username.startswith('@'):
                username = username[1:]
            
            self.cursor.execute('''
                UPDATE users 
                SET is_banned = 0 
                WHERE username = ?
            ''', (username,))
            
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Error unbanning user {username}: {e}")
            return False
    
    def is_user_banned(self, user_id: int) -> bool:
        """
        Проверка забанен ли пользователь
        
        Args:
            user_id: ID пользователя
            
        Returns:
            bool: True если забанен
        """
        try:
            self.cursor.execute('SELECT is_banned FROM users WHERE id = ?', (user_id,))
            result = self.cursor.fetchone()
            return result[0] == 1 if result else False
        except Exception as e:
            print(f"Error checking user ban status {user_id}: {e}")
            return False
    
    def get_user_stats(self) -> Dict[str, any]:
        """
        Получение статистики пользователей
        
        Returns:
            Dict: Статистика
        """
        try:
            stats = {}
            
            # Общее количество пользователей
            self.cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = self.cursor.fetchone()[0]
            
            # Активные пользователи (за последние 24 часа)
            self.cursor.execute('''
                SELECT COUNT(DISTINCT user_id) FROM active_sessions 
                WHERE last_activity > datetime('now', '-1 day')
            ''')
            stats['active_users_24h'] = self.cursor.fetchone()[0]
            
            # Забаненные пользователи
            self.cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            stats['banned_users'] = self.cursor.fetchone()[0]
            
            # Пользователи онлайн сейчас (за последние 5 минут)
            self.cursor.execute('''
                SELECT COUNT(DISTINCT user_id) FROM active_sessions 
                WHERE last_activity > datetime('now', '-5 minutes')
            ''')
            stats['online_now'] = self.cursor.fetchone()[0]
            
            # Самые активные пользователи
            self.cursor.execute('''
                SELECT username, first_name, total_clicks, product_clicks, last_seen
                FROM users 
                ORDER BY total_clicks DESC 
                LIMIT 10
            ''')
            stats['top_users'] = self.cursor.fetchall()
            
            return stats
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {}
    
    def get_product_stats(self) -> Dict[str, any]:
        """
        Получение статистики по товарам
        
        Returns:
            Dict: Статистика
        """
        try:
            stats = {}
            
            # Самые популярные товары (по кликам)
            self.cursor.execute('''
                SELECT p.id, p.name, p.category_slug, p.subcategory_slug, ps.clicks, ps.last_click
                FROM products p
                LEFT JOIN product_stats ps ON p.id = ps.product_id
                ORDER BY ps.clicks DESC 
                LIMIT 10
            ''')
            stats['top_products'] = self.cursor.fetchall()
            
            # Общее количество кликов
            self.cursor.execute('SELECT SUM(clicks) FROM product_stats')
            stats['total_clicks'] = self.cursor.fetchone()[0] or 0
            
            # Статистика по категориям
            self.cursor.execute('''
                SELECT c.name, COUNT(p.id) as product_count, 
                       SUM(ps.clicks) as total_clicks
                FROM categories c
                LEFT JOIN products p ON c.slug = p.category_slug
                LEFT JOIN product_stats ps ON p.id = ps.product_id
                GROUP BY c.slug, c.name
                ORDER BY total_clicks DESC
            ''')
            stats['category_stats'] = self.cursor.fetchall()
            
            # Статистика по подкатегориям
            self.cursor.execute('''
                SELECT s.name, c.name as category_name, COUNT(p.id) as product_count,
                       SUM(ps.clicks) as total_clicks
                FROM subcategories s
                JOIN categories c ON s.category_slug = c.slug
                LEFT JOIN products p ON s.slug = p.subcategory_slug AND s.type = p.type
                LEFT JOIN product_stats ps ON p.id = ps.product_id
                GROUP BY s.id, s.name, c.name
                ORDER BY total_clicks DESC
            ''')
            stats['subcategory_stats'] = self.cursor.fetchall()
            
            return stats
        except Exception as e:
            print(f"Error getting product stats: {e}")
            return {}
    
    def get_overall_stats(self) -> Dict[str, any]:
        """
        Получение общей статистики
        
        Returns:
            Dict: Общая статистика
        """
        try:
            stats = {}
            
            # Статистика пользователей
            user_stats = self.get_user_stats()
            stats.update(user_stats)
            
            # Статистика товаров
            product_stats = self.get_product_stats()
            stats.update(product_stats)
            
            # Количество товаров
            stats['total_products'] = self.get_all_products_count()
            
            # Количество категорий
            self.cursor.execute('SELECT COUNT(*) FROM categories')
            stats['total_categories'] = self.cursor.fetchone()[0]
            
            # Количество подкатегорий
            self.cursor.execute('SELECT COUNT(*) FROM subcategories')
            stats['total_subcategories'] = self.cursor.fetchone()[0]
            
            # Товары по типам
            self.cursor.execute('SELECT type, COUNT(*) FROM products GROUP BY type')
            stats['products_by_type'] = dict(self.cursor.fetchall())
            
            return stats
        except Exception as e:
            print(f"Error getting overall stats: {e}")
            return {}
    
    def get_detailed_database_stats(self) -> Dict[str, any]:
        """
        Получение детальной статистики базы данных
        
        Returns:
            Dict: Детальная статистика всех таблиц
        """
        try:
            stats = {}
            
            # Полная информация о категориях
            self.cursor.execute('SELECT id, slug, name, created_at FROM categories ORDER BY id')
            stats['categories'] = self.cursor.fetchall()
            
            # Полная информация о подкатегориях
            self.cursor.execute('''
                SELECT s.id, s.name, s.slug, s.type, c.name as category_name, s.created_at
                FROM subcategories s
                JOIN categories c ON s.category_slug = c.slug
                ORDER BY c.name, s.type, s.name
            ''')
            stats['subcategories'] = self.cursor.fetchall()
            
            # Полная информация о товарах
            self.cursor.execute('''
                SELECT p.id, p.name, p.category_slug, p.subcategory_slug, p.type, p.price, 
                       p.created_at, p.updated_at, COUNT(ps.clicks) as clicks
                FROM products p
                LEFT JOIN product_stats ps ON p.id = ps.product_id
                GROUP BY p.id
                ORDER BY p.category_slug, p.type, p.subcategory_slug, p.name
            ''')
            stats['products'] = self.cursor.fetchall()
            
            # Подробная информация о пользователях
            self.cursor.execute('''
                SELECT id, username, first_name, last_name, is_banned, 
                       first_seen, last_seen, total_clicks, product_clicks
                FROM users 
                ORDER BY last_seen DESC
            ''')
            stats['users'] = self.cursor.fetchall()
            
            # Статистика по кликам на товары
            self.cursor.execute('''
                SELECT ps.product_id, p.name, ps.clicks, ps.last_click
                FROM product_stats ps
                LEFT JOIN products p ON ps.product_id = p.id
                ORDER BY ps.clicks DESC
            ''')
            stats['product_stats'] = self.cursor.fetchall()
            
            # Активные сессии
            self.cursor.execute('''
                SELECT ases.user_id, u.username, ases.last_activity
                FROM active_sessions ases
                LEFT JOIN users u ON ases.user_id = u.id
                ORDER BY ases.last_activity DESC
            ''')
            stats['active_sessions'] = self.cursor.fetchall()
            
            # Версия базы данных
            self.cursor.execute('SELECT value FROM db_info WHERE key = "version"')
            version_result = self.cursor.fetchone()
            stats['db_version'] = version_result[0] if version_result else "Неизвестно"
            
            # Общая статистика
            self.cursor.execute('SELECT COUNT(*) FROM categories')
            stats['total_categories'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM subcategories')
            stats['total_subcategories'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM products')
            stats['total_products'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            stats['banned_users'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT SUM(clicks) FROM product_stats')
            stats['total_clicks'] = self.cursor.fetchone()[0] or 0
            
            return stats
        except Exception as e:
            print(f"Error getting detailed database stats: {e}")
            return {}
    
    def get_all_usernames(self) -> List[str]:
        """
        Получение всех username из базы данных
        
        Returns:
            List[str]: Список username
        """
        try:
            self.cursor.execute('SELECT username FROM users WHERE username IS NOT NULL AND username != ""')
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"Error getting usernames: {e}")
            return []
    
    def clear_database(self) -> bool:
        """
        Очистка всей базы данных
        
        Returns:
            bool: True если успешно
        """
        try:
            # Удаляем все таблицы
            self.cursor.execute('DELETE FROM product_stats')
            self.cursor.execute('DELETE FROM active_sessions')
            self.cursor.execute('DELETE FROM users')
            self.cursor.execute('DELETE FROM products')
            self.cursor.execute('DELETE FROM subcategories')
            self.cursor.execute('DELETE FROM categories')
            self.cursor.execute('DELETE FROM db_info')
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error clearing database: {e}")
            return False
    
    def reload_database(self) -> bool:
        """
        Перезагрузка базы данных (обновление структуры без очистки данных)
        
        Returns:
            bool: True если успешно
        """
        try:
            print("🔄 Начинаем перезагрузку базы данных...")
            
            # 1. Создаем резервную копию на всякий случай
            backup_file = self.backup_database()
            print(f"📁 Создана резервная копия: {backup_file}")
            
            # 2. Проверяем и обновляем структуру базы данных
            print("🔧 Проверяем и обновляем структуру БД...")
            self._check_and_upgrade_database()
            
            # 3. Проверяем целостность базы данных
            print("🔍 Проверяем целостность данных...")
            integrity_result = self.check_integrity()
            
            if integrity_result['status'] == 'ok':
                print("✅ База данных успешно обновлена и проверена!")
                return True
            else:
                print("⚠️ База данных обновлена, но есть проблемы с целостностью:")
                for error in integrity_result.get('errors', []):
                    print(f"  ❌ {error}")
                for warning in integrity_result.get('warnings', []):
                    print(f"  ⚠️ {warning}")
                return True  # Все равно возвращаем True, так как база рабочая
            
        except Exception as e:
            print(f"❌ Ошибка при перезагрузке базы данных: {e}")
            
            # Пробуем восстановить из резервной копии
            try:
                if backup_file and os.path.exists(backup_file):
                    import shutil
                    shutil.copy2(backup_file, 'products.db')
                    print(f"🔄 Восстановлено из резервной копии: {backup_file}")
            except Exception as restore_error:
                print(f"❌ Ошибка при восстановлении из резервной копии: {restore_error}")
            
            return False
    
    def _load_test_data(self) -> bool:
        """
        Загрузка тестовых данных (внутренний метод)
        
        Returns:
            bool: True если успешно
        """
        try:
            # Добавляем категории
            categories = [
                ("🧱 Lego (Все ответвления)", "lego"),
                ("🧩 Аналог Lego (Cada, Area-X, Oloey и тд)", "analog"),
                ("🎭 Funko pop", "funko")
            ]
            
            for name, slug in categories:
                self.add_category(name, slug)
            
            # Добавляем подкатегории для Funko (Предзаказ)
            funko_preorder_subcategories = [
                ("🎬 Фильмы", "movies"),
                ("🎮 Игры", "games"),
                ("🇯🇵 Аниме", "anime"),
                ("📺 Сериалы", "series"),
                ("🐰 Мультфильмы", "cartoons"),
                ("🎭 Другое", "other")
            ]
            
            for name, slug in funko_preorder_subcategories:
                self.add_subcategory("funko", name, slug, "preorder")
            
            # Добавляем подкатегории для Funko (В наличии)
            funko_instock_subcategories = [
                ("🎬 Фильмы", "movies"),
                ("🎮 Игры", "games"),
                ("🇯🇵 Аниме", "anime"),
                ("📺 Сериалы", "series"),
                ("🐰 Мультфильмы", "cartoons"),
                ("🎭 Другое", "other")
            ]
            
            for name, slug in funko_instock_subcategories:
                self.add_subcategory("funko", name, slug, "instock")
            
            # Добавляем подкатегории для Lego (В наличии)
            lego_subcategories = [
                ("🚗 Машины", "cars"),
                ("🏰 Строения", "buildings"),
                ("⚔️ Фэнтези", "fantasy"),
                ("🧩 Другое", "other")
            ]
            
            for name, slug in lego_subcategories:
                self.add_subcategory("lego", name, slug, "instock")
            
            # Добавляем товары
            products = [
                # Funko - Предзаказ - Фильмы
                ("funko", "preorder", "movies", "Funko Pop Jason", "3300 ₽", 
                 "✅Оригинальный Funko Pop! Jason по мотивам фильма «Пятница 13-e» #1964\n❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
                 "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
                 "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
                 "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
                 "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
                 ["img/FunkoPopJason.webp", "img/FunkoPopJason2.webp", "img/FunkoPopJason3.webp", "img/FunkoPopJason4.webp"],
                 ["пятница 13", "джейсон", "хоррор", "фильм", "funko"]),
                
                # Funko - Предзаказ - Игры
                ("funko", "preorder", "games", "Funko Pop FnaF endo-02", "3000 ₽", 
                 "Funko POP! Games FNAF Endo-02 NYCC25 (#1105) Лимитированная коллекция 2025 года. QR - замазан авито\n"
                 "❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
                 "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
                 "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
                 "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
                 "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
                 ["img/FunkoPopFnaFEndo-02.webp", "img/FunkoPopFnaFEndo-02_2.webp", 
                  "img/FunkoPopFnaFEndo-02_3.webp", "img/FunkoPopFnaFEndo-02_4.webp"],
                 ["fnaf", "five nights at freddys", "эндо", "игра", "хоррор"]),
                
                # Funko - Предзаказ - Сериалы
                ("funko", "preorder", "series", "Funko POP TV осд S5 Dustin Henderson", "3200 ₽", 
                 "✅Оригинальный Funko POP! TV Stranger Things S5 Dustin Henderson (Exc) (1800) 88556\n"
                 "❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
                 "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
                 "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
                 "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
                 "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
                 ["img/FunkoPOPTVS5DustinHenderson.webp", "img/FunkoPOPTVS5DustinHenderson2.webp",
                  "img/FunkoPOPTVS5DustinHenderson3.webp"],
                 ["stranger things", "очевидные странности", "дастин", "сериал", "научная фантастика"]),
                
                # Funko - В наличии - Игры
                ("funko", "instock", "games", "Funko Pop fnaf Withered Chica", "1170 ₽", 
                 "Новый оригинальный Funko Pop! По мотивам игры Fnaf.\n✅ В наличии через несколько дней!\nВозможна бронь.\n\n"
                 "🤔Почему именно мы?\nМы сами коллекционеры Funko\n• Мы сами коллекционеры Funko и прекрасно понимаем, что никому не хочется видеть рваные коробки и реплики.\n"
                 "• Продаем фигурки дешевле рынка / тех которых нет на маркетплейсах\n• Фигурки в идеальном состоянии, с коробками\n"
                 "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
                 ["img/FunkoPopFnafWitheredChica.webp", "img/FunkoPopFnafWitheredChica2.webp",
                  "img/FunkoPopFnafWitheredChica3.webp"],
                 ["fnaf", "чика", "игра", "хоррор", "в наличии"]),
                
                # Lego - В наличии - Машины
                ("lego", "instock", "cars", "Конструктор Танк Tiger", "1350 ₽", 
                 "Конструктор вдохновленный танком Tiger.\n🎁Подойдет как для детей, так и для взрослых / как подарок, так и для коллекции.",
                 ["img/LegoTankTiger.webp", "img/LegoTankTiger2.webp"],
                 ["танк", "тигр", "военный", "конструктор", "lego"]),
                
                # Аналог Lego - В наличии - Машины
                ("analog", "instock", "cars", "Lego Ferrari 6+", "3400 ₽", 
                 "Конструктор Ferrari.\nСтильный дизайн, отличная детализация – выглядит солидно.\n🎁 Подойдёт как подарок, для игры или в коллекцию.",
                 ["img/LegoFerrari6_0.webp", "img/LegoFerrari6_1.webp", "img/LegoFerrari6_2.webp"],
                 ["феррари", "машина", "спорткар", "конструктор", "аналог lego"]),

                ("analog", "instock", "cars", "Formula F1", "3200 ₽", 
                 "Конструктор Formula F1.\nКачественная детализация, прочный корпус.\n🎁 Подойдёт как подарок, для игры или в коллекцию.",
                 ["img/LegoFerrari6_0.webp"],
                 ["формула 1", "f1", "гоночный", "конструктор", "аналог lego"]),
                
                # Funko - Предзаказ - Аниме
                ("funko", "preorder", "anime", "Funko Pop Naruto", "2800 ₽", 
                 "✅Оригинальный Funko Pop! Naruto Uzumaki\n❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
                 "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
                 "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.",
                 ["img/no_photo.webp"],
                 ["наруто", "аниме", "наруто узумаки", "шипуден", "манга"]),
            ]
            
            for product in products:
                self.add_product(*product)
            
            # Устанавливаем версию базы данных
            self.cursor.execute('INSERT OR REPLACE INTO db_info (key, value) VALUES ("version", ?)', (str(self._current_version),))
            self.conn.commit()
            
            return True
        except Exception as e:
            print(f"Error loading test data: {e}")
            return False
    
    def backup_database(self, backup_name: str = None) -> str:
        """
        Создание резервной копии базы данных
        
        Args:
            backup_name: Имя файла резервной копии
            
        Returns:
            str: Путь к файлу резервной копии
        """
        try:
            import datetime
            
            if not backup_name:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Получаем статистику для имени файла
                products_count = self.get_all_products_count()
                categories_count = len(self.get_categories())
                
                backup_name = f"backup_{timestamp}_p{products_count}_c{categories_count}.db"
            
            import shutil
            shutil.copy2('products.db', backup_name)
            
            # Также сохраняем информацию о резервной копии
            backup_info = {
                'timestamp': datetime.datetime.now().isoformat(),
                'products_count': products_count,
                'categories_count': categories_count,
                'users_count': self.get_user_stats().get('total_users', 0),
                'version': self._current_version
            }
            
            import json
            info_file = backup_name.replace('.db', '_info.json')
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(backup_info, f, ensure_ascii=False, indent=2)
            
            print(f"✅ Создана резервная копия: {backup_name}")
            print(f"   📊 Информация сохранена в: {info_file}")
            
            return backup_name
        except Exception as e:
            print(f"❌ Ошибка при создании резервной копии: {e}")
            return ""
    
    def check_integrity(self) -> Dict[str, any]:
        """
        Проверка целостности базы данных
        
        Returns:
            Dict: Результаты проверки
        """
        result = {
            'status': 'ok',
            'errors': [],
            'warnings': [],
            'tables': {}
        }
        
        try:
            # Проверяем существование таблиц
            tables = ['categories', 'subcategories', 'products', 'users', 'product_stats', 'active_sessions', 'db_info']
            for table in tables:
                self.cursor.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'")
                exists = self.cursor.fetchone()[0] > 0
                result['tables'][table] = '✅ существует' if exists else '❌ отсутствует'
                
                if not exists:
                    result['errors'].append(f"Таблица {table} отсутствует")
            
            # Проверяем данные в таблицах
            self.cursor.execute('SELECT COUNT(*) FROM categories')
            result['categories_count'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM subcategories')
            result['subcategories_count'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM products')
            result['products_count'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM users')
            result['users_count'] = self.cursor.fetchone()[0]
            
            # Проверяем отсутствующие ссылки (foreign keys)
            # Категории товаров, которых нет в таблице categories
            self.cursor.execute('''
                SELECT DISTINCT category_slug FROM products 
                WHERE category_slug NOT IN (SELECT slug FROM categories)
            ''')
            missing_categories = self.cursor.fetchall()
            if missing_categories:
                for cat in missing_categories:
                    result['errors'].append(f"Товары ссылаются на несуществующую категорию: {cat[0]}")
            
            # Подкатегории товаров, которых нет в таблице subcategories
            self.cursor.execute('''
                SELECT DISTINCT subcategory_slug FROM products 
                WHERE subcategory_slug IS NOT NULL 
                AND subcategory_slug NOT IN (SELECT slug FROM subcategories)
            ''')
            missing_subcategories = self.cursor.fetchall()
            if missing_subcategories:
                for subcat in missing_subcategories:
                    result['warnings'].append(f"Товары ссылаются на несуществующую подкатегорию: {subcat[0]}")
            
            # Проверяем версию БД
            self.cursor.execute('SELECT value FROM db_info WHERE key = "version"')
            version_result = self.cursor.fetchone()
            if version_result:
                result['db_version'] = version_result[0]
            else:
                result['warnings'].append("Версия базы данных не указана")
            
            # Если есть ошибки, меняем статус
            if result['errors']:
                result['status'] = 'error'
            elif result['warnings']:
                result['status'] = 'warning'
            
        except Exception as e:
            result['status'] = 'error'
            result['errors'].append(f"Ошибка при проверке целостности: {str(e)}")
        
        return result
    
    def close(self) -> None:
        """Закрытие соединения с БД"""
        self.conn.close()

def init_test_data() -> bool:
    """
    Инициализация тестовых данных с подкатегориями
    
    Returns:
        bool: True если успешно
    """
    print("🔄 Инициализация базы данных...")
    
    # Создаем папку для фото если её нет
    os.makedirs('img', exist_ok=True)
    
    db = Database()
    
    # Очищаем таблицы
    print("🧹 Очистка старых данных...")
    db.cursor.execute('DELETE FROM products')
    db.cursor.execute('DELETE FROM subcategories')
    db.cursor.execute('DELETE FROM categories')
    db.cursor.execute('DELETE FROM users')
    db.cursor.execute('DELETE FROM product_stats')
    db.cursor.execute('DELETE FROM active_sessions')
    db.cursor.execute('DELETE FROM db_info')
    db.conn.commit()
    
    # Загружаем тестовые данные
    print("📂 Добавление категорий...")
    categories = [
        ("🧱 Lego (Все ответвления)", "lego"),
        ("🧩 Аналог Lego (Cada, Area-X, Oloey и тд)", "analog"),
        ("🎭 Funko pop", "funko")
    ]
    
    for name, slug in categories:
        db.add_category(name, slug)
    
    # Добавляем подкатегории
    print("📚 Добавление подкатегорий...")
    
    # Funko - Предзаказ
    funko_preorder_subcategories = [
        ("🎬 Фильмы", "movies"),
        ("🎮 Игры", "games"),
        ("🇯🇵 Аниме", "anime"),
        ("📺 Сериалы", "series"),
        ("🐰 Мультфильмы", "cartoons"),
        ("🎭 Другое", "other")
    ]
    
    for name, slug in funko_preorder_subcategories:
        db.add_subcategory("funko", name, slug, "preorder")
    
    # Funko - В наличии
    funko_instock_subcategories = [
        ("🎬 Фильмы", "movies"),
        ("🎮 Игры", "games"),
        ("🇯🇵 Аниме", "anime"),
        ("📺 Сериалы", "series"),
        ("🐰 Мультфильмы", "cartoons"),
        ("🎭 Другое", "other")
    ]
    
    for name, slug in funko_instock_subcategories:
        db.add_subcategory("funko", name, slug, "instock")
    
    # Lego - В наличии
    lego_subcategories = [
        ("🚗 Машины", "cars"),
        ("🏰 Строения", "buildings"),
        ("⚔️ Фэнтези", "fantasy"),
        ("🧩 Другое", "other")
    ]
    
    for name, slug in lego_subcategories:
        db.add_subcategory("lego", name, slug, "instock")
    
    # Аналог Lego - В наличии
    analog_subcategories = [
        ("🚗 Машины", "cars"),
        ("🏗️ Техника", "tech"),
        ("🧩 Другое", "other")
    ]
    
    for name, slug in analog_subcategories:
        db.add_subcategory("analog", name, slug, "instock")
    
    # Добавляем товары с тегами
    print("📦 Добавление товаров...")
    products = [
        # Funko - Предзаказ - Фильмы
        ("funko", "preorder", "movies", "Funko Pop Jason", "3300 ₽", 
         "✅Оригинальный Funko Pop! Jason по мотивам фильма «Пятница 13-e» #1964\n❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
         "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
         "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
         "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
         "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
         ["img/FunkoPopJason.webp", "img/FunkoPopJason2.webp", "img/FunkoPopJason3.webp", "img/FunkoPopJason4.webp"],
         ["пятница 13", "джейсон", "хоррор", "фильм", "funko"]),
        
        # Funko - Предзаказ - Игры
        ("funko", "preorder", "games", "Funko Pop FnaF endo-02", "3000 ₽", 
         "Funko POP! Games FNAF Endo-02 NYCC25 (#1105) Лимитированная коллекция 2025 года. QR - замазан авито\n"
         "❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
         "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
         "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
         "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
         "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
         ["img/FunkoPopFnaFEndo-02.webp", "img/FunkoPopFnaFEndo-02_2.webp", 
          "img/FunkoPopFnaFEndo-02_3.webp", "img/FunkoPopFnaFEndo-02_4.webp"],
         ["fnaf", "five nights at freddys", "эндо", "игра", "хоррор"]),
        
        # Funko - Предзаказ - Сериалы
        ("funko", "preorder", "series", "Funko POP TV осд S5 Dustin Henderson", "3200 ₽", 
         "✅Оригинальный Funko POP! TV Stranger Things S5 Dustin Henderson (Exc) (1800) 88556\n"
         "❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
         "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
         "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.\n\n"
         "Почему именно мы?\n• Мы сами коллекционеры Funko\n• Продаем фигурки дешевле рынка\n• Фигурки в идеальном состоянии, с коробками\n"
         "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
         ["img/FunkoPOPTVS5DustinHenderson.webp", "img/FunkoPOPTVS5DustinHenderson2.webp",
          "img/FunkoPOPTVS5DustinHenderson3.webp"],
         ["stranger things", "очевидные странности", "дастин", "сериал", "научная фантастика"]),
        
        # Funko - В наличии - Игры
        ("funko", "instock", "games", "Funko Pop fnaf Withered Chica", "1170 ₽", 
         "Новый оригинальный Funko Pop! По мотивам игры Fnaf.\n✅ В наличии через несколько дней!\nВозможна бронь.\n\n"
         "🤔Почему именно мы?\nМы сами коллекционеры Funko\n• Мы сами коллекционеры Funko и прекрасно понимаем, что никому не хочется видеть рваные коробки и реплики.\n"
         "• Продаем фигурки дешевле рынка / тех которых нет на маркетплейсах\n• Фигурки в идеальном состоянии, с коробками\n"
         "• Берём только проверенные франшизы\n• Упаковываем аккуратно, защищаем от повреждений",
         ["img/FunkoPopFnafWitheredChica.webp", "img/FunkoPopFnafWitheredChica2.webp",
          "img/FunkoPopFnafWitheredChica3.webp"],
         ["fnaf", "чика", "игра", "хоррор", "в наличии"]),
        
        # Lego - В наличии - Машины
        ("lego", "instock", "cars", "Конструктор Танк Tiger", "1350 ₽", 
         "Конструктор вдохновленный танком Tiger.\n🎁Подойдет как для детей, так и для взрослых / как подарок, так и для коллекции.",
         ["img/LegoTankTiger.webp", "img/LegoTankTiger2.webp"],
         ["танк", "тигр", "военный", "конструктор", "lego"]),
        
        # Аналог Lego - В наличии - Машины
        ("analog", "instock", "cars", "Lego Ferrari 6+", "3400 ₽", 
         "Конструктор Ferrari.\nСтильный дизайн, отличная детализация – выглядит солидно.\n🎁 Подойдёт как подарок, для игры или в коллекцию.",
         ["img/LegoFerrari6_0.webp", "img/LegoFerrari6_1.webp", "img/LegoFerrari6_2.webp"],
         ["феррари", "машина", "спорткар", "конструктор", "аналог lego"]),

        ("analog", "instock", "cars", "Formula F1", "3200 ₽", 
         "Конструктор Formula F1.\nКачественная детализация, прочный корпус.\n🎁 Подойдёт как подарок, для игры или в коллекцию.",
         ["img/LegoFerrari6_0.webp"],
         ["формула 1", "f1", "гоночный", "конструктор", "аналог lego"]),
        
        # Funko - Предзаказ - Аниме
        ("funko", "preorder", "anime", "Funko Pop Naruto", "2800 ₽", 
         "✅Оригинальный Funko Pop! Naruto Uzumaki\n❗️Предзаказ с партнерского склада (доставка до 7 дней)\n\n"
         "❓Почему товара нет на руках?\nМы – ещё небольшой магазинчик и не держим весь ассортимент у себя на складе.\n"
         "После оформления заказа товар отправляется с партнерского склада – это позволяет держать цены ниже и предлагать больше позиций.",
         ["img/no_photo.webp"],
         ["наруто", "аниме", "наруто узумаки", "шипуден", "манга"]),
    ]
    
    for i, product in enumerate(products, 1):
        db.add_product(*product)
        print(f"  [{i}/{len(products)}] Добавлен: {product[3]}")
    
    # Статистика
    categories_count = len(db.get_categories())
    subcategories_count = len(db.get_all_subcategories())
    products_count = db.get_all_products_count()
    
    print(f"\n✅ Инициализация завершена!")
    print(f"📂 Создано категорий: {categories_count}")
    print(f"📚 Создано подкатегорий: {subcategories_count}")
    print(f"📦 Добавлено товаров: {products_count}")
    
    # Проверка целостности
    print("\n🔍 Проверка целостности базы данных...")
    integrity = db.check_integrity()
    
    if integrity['status'] == 'ok':
        print("✅ Целостность базы данных в порядке")
    else:
        print("⚠️ Обнаружены проблемы с целостностью:")
        for error in integrity.get('errors', []):
            print(f"  ❌ {error}")
        for warning in integrity.get('warnings', []):
            print(f"  ⚠️ {warning}")
    
    # Проверяем наличие фото файлов
    print("\n🔍 Проверка файлов фото...")
    all_photos = []
    categories = db.get_categories()
    for slug in categories.keys():
        for type_ in ['preorder', 'instock']:
            products_list = db.get_products_by_category_and_type(slug, type_)
            for p in products_list:
                all_photos.extend(p['photo_urls'])
    
    missing_photos = []
    for photo in set(all_photos):  # Уникальные фото
        if not os.path.exists(photo):
            missing_photos.append(photo)
    
    if missing_photos:
        print(f"⚠️ Отсутствуют {len(missing_photos)} файлов фото:")
        for photo in missing_photos[:10]:  # Показываем первые 10
            print(f"  ❌ {photo}")
        if len(missing_photos) > 10:
            print(f"  ... и ещё {len(missing_photos) - 10} файлов")
        print(f"\n💡 Поместите недостающие файлы в папку img/")
    else:
        print("✅ Все файлы фото найдены!")
    
    db.close()
    return True

def check_database_integrity() -> Dict[str, any]:
    """
    Проверка целостности базы данных
    
    Returns:
        Dict: Результаты проверки
    """
    db = Database()
    
    result = {
        'categories': 0,
        'subcategories': 0,
        'products': 0,
        'photos_total': 0,
        'photos_available': 0,
        'photos_missing': 0,
        'categories_list': [],
        'missing_files': [],
        'integrity': None
    }
    
    # Проверяем целостность БД
    result['integrity'] = db.check_integrity()
    
    # Категории
    categories = db.get_categories()
    result['categories'] = len(categories)
    result['categories_list'] = list(categories.values())
    
    # Подкатегории
    result['subcategories'] = len(db.get_all_subcategories())
    
    # Товары и фото
    all_photos = []
    for slug in categories.keys():
        for type_ in ['preorder', 'instock']:
            products = db.get_products_by_category_and_type(slug, type_)
            for product in products:
                result['products'] += 1
                result['photos_total'] += len(product['photo_urls'])
                all_photos.extend(product['photo_urls'])
    
    # Проверяем файлы
    unique_photos = set(all_photos)
    for photo in unique_photos:
        if os.path.exists(photo):
            result['photos_available'] += 1
        else:
            result['photos_missing'] += 1
            result['missing_files'].append(photo)
    
    db.close()
    return result

if __name__ == "__main__":
    print("=" * 60)
    print("🛠️  ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ASIAHAPPY")
    print("=" * 60)
    
    # Создаем объект базы данных для проверки версии
    db = Database()
    db.close()
    
    init_test_data()
    
    # Проверка целостности
    print(f"\n{'=' * 60}")
    print("🔍 ПРОВЕРКА ЦЕЛОСТНОСТИ БАЗЫ ДАННЫХ")
    print("=" * 60)
    
    check_result = check_database_integrity()
    
    print(f"📂 Категории: {check_result['categories']}")
    print(f"📚 Подкатегории: {check_result['subcategories']}")
    print(f"📦 Товары: {check_result['products']}")
    print(f"📸 Всего фото: {check_result['photos_total']}")
    print(f"✅ Фото доступно: {check_result['photos_available']}")
    print(f"❌ Фото отсутствует: {check_result['photos_missing']}")
    
    # Выводим информацию о целостности
    if check_result['integrity']:
        integrity = check_result['integrity']
        print(f"\n🔧 Статус целостности: {integrity['status']}")
        
        if integrity.get('errors'):
            print(f"❌ Ошибки: {len(integrity['errors'])}")
            for error in integrity['errors'][:3]:
                print(f"  • {error}")
        
        if integrity.get('warnings'):
            print(f"⚠️ Предупреждения: {len(integrity['warnings'])}")
            for warning in integrity['warnings'][:3]:
                print(f"  • {warning}")
    
    if check_result['missing_files']:
        print(f"\n⚠️ Отсутствующие файлы:")
        for file in check_result['missing_files'][:5]:
            print(f"  {file}")
        if len(check_result['missing_files']) > 5:
            print(f"  ... и ещё {len(check_result['missing_files']) - 5} файлов")
    
    print(f"\n{'=' * 60}")
    print("✅ БАЗА ДАННЫХ ГОТОВА К ИСПОЛЬЗОВАНИЮ")
    print("=" * 60)