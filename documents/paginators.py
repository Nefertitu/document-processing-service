from rest_framework.pagination import PageNumberPagination


class DocumentPaginator(PageNumberPagination):
    """Пагинатор для вывода документов"""

    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 10


class QueueItemPaginator(PageNumberPagination):
    """Пагинатор для вывода документов очереди"""

    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 10

class ApprovalItemPaginator(PageNumberPagination):
    """Пагинатор для вывода очередей с документами"""

    page_size = 3
    page_size_query_param = "page_size"
    max_page_size = 5
