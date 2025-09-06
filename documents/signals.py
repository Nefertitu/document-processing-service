# from django.db.models.signals import post_save
# from django.dispatch import receiver
#
#
# @receiver(post_save)
# def handle_new_document(sender, instance, created, **kwargs):
#     """Обработка нового документа"""
#
#     from .models import ApprovalQueue, Document
#     if sender == Document:
#         if created and instance.status == "pending" and not instance.assigned_admin:
#             admin = instance.assign_admin()
#             admin.save()
#
#             if admin:
#                 queue, created = ApprovalQueue.objects.get_or_create(approver=admin)
#                 queue.add_document(instance)
#         elif instance.status in ['approved', 'rejected'] and not instance.reviewed_by:
#             from django.contrib.auth import get_user_model
#             User = get_user_model()
