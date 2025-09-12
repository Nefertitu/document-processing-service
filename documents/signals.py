# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from .models import QueueItem
#
#
# @receiver(post_save, sender=QueueItem)
# def transfer_data_to_document(sender, instance, **kwargs):
#     """Переносит данные из QueueItem в Document после сохранения"""
#     if hasattr(instance, 'temp_review_comment') and instance.temp_review_comment:
#         instance.document.review_comment = instance.temp_review_comment
#         instance.document.save()
#
#     if hasattr(instance, 'temp_file_answer') and instance.temp_file_answer:
#         instance.document.file_answer = instance.temp_file_answer
#         instance.document.save()