from rest_framework import serializers
from backend.apps.accounts.serializers import StrictSerializer, StrictStringField


class OperationalConfigSerializer(StrictSerializer):
    enabled_days = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False)
    open_time = StrictStringField(max_length=5, required=False)
    close_time = StrictStringField(max_length=5, required=False)
    primary_email = serializers.EmailField(max_length=254, required=False)
    backup_email = serializers.EmailField(max_length=254, required=False)