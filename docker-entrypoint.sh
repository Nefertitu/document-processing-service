set -e


mkdir -p /app/media/documents /app/media/temp_uploads /app/media/temp_answers
mkdir -p /app/static /app/staticfiles
chmod -R 755 /app/media /app/static /app/staticfiles

exec "$@"