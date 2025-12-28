import os
import sqlite3
import json

def check_photo_files():
    """Проверить какие фото есть в папке img"""
    print("📁 Содержимое папки img:")
    
    if not os.path.exists('img'):
        print("❌ Папка 'img' не найдена!")
        return
    
    files = os.listdir('img')
    for file in sorted(files):
        print(f"  📄 {file}")
    
    print(f"\n📊 Всего файлов: {len(files)}")

def check_database():
    """Проверить какие фото указаны в базе данных"""
    print("\n📊 Данные из базы данных:")
    
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    
    # Проверить товары
    cursor.execute('SELECT id, name, photo_urls FROM products ORDER BY id')
    products = cursor.fetchall()
    
    total_products = 0
    total_photos = 0
    missing_photos = 0
    
    for product in products:
        product_id, name, photo_urls_json = product
        total_products += 1
        
        print(f"\n{'='*50}")
        print(f"ID: {product_id}")
        print(f"Название: {name}")
        
        try:
            photo_urls = json.loads(photo_urls_json) if photo_urls_json else []
            print(f"Фото в БД: {len(photo_urls)} шт.")
            
            for i, photo_url in enumerate(photo_urls, 1):
                total_photos += 1
                
                # Проверить существует ли файл
                if photo_url.startswith('/'):
                    file_path = f".{photo_url}"
                else:
                    file_path = photo_url
                
                exists = os.path.exists(file_path)
                status = "✅ ЕСТЬ" if exists else "❌ НЕТ"
                
                if not exists:
                    missing_photos += 1
                
                print(f"  {i}. {photo_url} - {status}")
                
        except json.JSONDecodeError:
            print("❌ Ошибка при чтении JSON с фото")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    conn.close()
    
    print(f"\n{'='*50}")
    print(f"📊 ИТОГО:")
    print(f"• Товаров: {total_products}")
    print(f"• Всего фото в БД: {total_photos}")
    print(f"• Отсутствует фото: {missing_photos}")
    print(f"• Доступно фото: {total_photos - missing_photos}")

if __name__ == "__main__":
    check_photo_files()
    if os.path.exists('products.db'):
        check_database()
    else:
        print("\n❌ База данных 'products.db' не найдена")
        print("Запустите сначала: python init_db.py")