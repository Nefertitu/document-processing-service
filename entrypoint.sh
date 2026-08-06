set -e  # Останавливаемся при ошибке

echo "=========================================="
echo "ЗАПУСК ENTRYPOINT ДЛЯ $SERVICE_NAME"
echo "=========================================="


log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Ожидаем готовности базы данных
echo "Ожидание базы данных..."
while ! nc -z $POSTGRES_HOST 5432; do
    echo "База данных недоступна, ожидание..."
    sleep 1
done
echo "✅ База данных готова!"

# Выполняем миграции (только если не отключено)
if [ "$SKIP_MIGRATIONS" != "true" ]; then
    echo "Выполнение миграций..."
    python manage.py migrate --noinput
    echo "✅ Миграции выполнены"
else
    echo "Пропускаем миграции (SKIP_MIGRATIONS=true)"
fi

# Загружаем фикстуры (только если не отключено и если файл существует)
if [ "$SKIP_FIXTURES" != "true" ] && [ -f "groups.json" ]; then
    echo "Загрузка групп из фикстуры..."
    python manage.py loaddata groups.json || echo "⚠️ Группы уже загружены"
else
    echo "Пропускаем загрузку фикстур"
fi

# Создаем пользователей (единая команда!)
if [ "$SKIP_USER_CREATION" != "true" ]; then
    log "Создание пользователей..."
    python manage.py create_users || log "⚠️ Ошибка при создании пользователей"
fi

# Собираем статику (только если не отключено)
if [ "$SKIP_COLLECTSTATIC" != "true" ]; then
    echo "Сбор статических файлов..."
    python manage.py collectstatic --noinput
    echo "✅ Статика собрана"
fi

echo "=========================================="
echo "✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА"
echo "=========================================="

# Запускаем основную команду
exec "$@"