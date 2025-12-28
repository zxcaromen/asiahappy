from database import init_test_data

if __name__ == "__main__":
    print("=" * 60)
    print("🛠️  ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ASIAHAPPY")
    print("=" * 60)
    
    success = init_test_data()
    
    if success:
        print("\n✅ База данных успешно создана и заполнена!")
        print("\n🚀 Теперь можно запустить бота: python mains.py")
    else:
        print("\n❌ Ошибка при создании базы данных!")