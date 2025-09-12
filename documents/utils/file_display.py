from django.utils.safestring import mark_safe
from django.utils.html import format_html


def get_files_display_html(document_files):
    """Отображает все файлы документа в очереди"""

    if not document_files:
        return "Документ не найден"

    links = []

    viewable_extensions = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'txt', 'html', 'htm']

    icon_map = {
        'doc': '📝', 'docx': '📝', 'txt': '📄',
        'xls': '📊', 'xlsx': '📊', '7z': '📦',
        'rar': '📦', 'zip': '📦', 'gif': '🏞️',
        'jpg': '🏞️', 'jpeg': '🏞️', 'png': '🏞️',
        'htm': '🌐', 'html': '🌐', 'pdf': '📄',
        'py': '🐍', 'mp3': '🎵', 'avi': '🎬', 'mp4': '🎬',
    }

    for doc_file in document_files:
        if doc_file.file:
            try:
                file_name = doc_file.original_name or doc_file.file.name.split('/')[-1]
                file_extension = file_name.split('.')[-1].lower() if '.' in file_name else 'file'

                file_icon = icon_map.get(file_extension, '📁')
                file_name = file_icon

                try:
                    file_size = doc_file.file.size
                    if file_size < 1024:
                        size_str = f"{file_size} B"
                    elif file_size < 1024 * 1024:
                        size_str = f"{file_size / 1024:.1f} KB"
                    else:
                        size_str = f"{file_size / (1024 * 1024):.1f} MB"
                except:
                    size_str = "неизвестный размер"

                if file_extension in viewable_extensions:

                    link_html = format_html(
                        '<div style="display: flex; gap: 5px; align-items: center; margin-bottom: 8px;">'
                        '<a href="{}" target="_blank" style="background: #417690; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
                        '🔍'
                        '</a>'
                        '<a href="{}" download style="background: #205067; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
                        '⬇️'
                        '</a>'
                        '<span style="color: #666; font-size: 13px; margin-left: 5px;">{} <span style="color: #999; font-size: 11px;">(.{})</span></span>'
                        '</div>'
                        '<span style="color: #999; font-size: 11px;">размер: {}</span>'
                        '</div>'
                        '</div>',
                        doc_file.file.url,
                        doc_file.file.url,
                        file_name,
                        file_extension.upper(),
                        size_str
                    )
                    links.append(link_html)

                else:

                    link_html = format_html(
                        '<div style="display: flex; gap: 5px; align-items: center; margin-bottom: 8px;">'
                        '<a href="{}" download style="background: #205067; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
                        '⬇️'
                        '</a>'
                        '<span style="color: #666; font-size: 13px; margin-left: 5px;">{} <span style="color: #999; font-size: 11px;">(.{})</span></span>'
                        '</div>'
                        '<span style="color: #999; font-size: 11px;">размер: {}</span>'
                        '</div>'
                        '</div>',
                        doc_file.file.url,
                        file_name,
                        file_extension.upper(),
                        size_str
                    )
                    links.append(link_html)

            except Exception as e:
                print(f"Ошибка при обработке файла {doc_file.id}: {e}")
                continue

    if links:
        combined_html = ''.join(str(link) for link in links)
        return mark_safe(combined_html)
    return "Нет файлов"


def get_file_answer_display(document_file):
    """Отображает все файлы документа в очереди"""


    if not document_file:
        return ""

    try:

        file_name = document_file.file.name.split('/')[-1]
        file_extension = file_name.split('.')[-1].lower() if '.' in file_name else 'file'

        try:
            file_size = document_file.file.size
            if file_size < 1024:
                size_str = f"{file_size} B"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
        except:
            size_str = "нет данных о размере файла"

        icon_map = {
            'pdf': '📄', 'doc': '📝', 'docx': '📝',
            'xls': '📊', 'xlsx': '📊', 'jpg': '🏞️',
            'jpeg': '🏞️', 'png': '🏞️', 'zip': '📦', 'rar': '📦'
        }
        icon = icon_map.get(file_extension, '📁')
        file_name = icon

        return format_html(
            '<div style="display: flex; gap: 5px; align-items: center; margin-bottom: 8px;">'
            '<a href="{}" target="_blank" style="background: #417690; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
            '🔍'
            '</a>'
            '<a href="{}" download style="background: #205067; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
            '⬇️'
            '</a>'
            '<span style="color: #666; font-size: 13px; margin-left: 5px;">{} <span style="color: #999; font-size: 11px;">(.{})</span></span>'
            '</div>'
            '<span style="color: #999; font-size: 11px;">размер: {}</span>'
            '</div>'
            '</div>',
            document_file.url,
            document_file.url,
            file_name,
            file_extension.upper(),
            size_str
        )

    except Exception as e:
        print(f"Ошибка при обработке файла {document_file.name}: {e}")