from rest_framework import serializers
from .models import StockData, CalendarEvent, QuarterlyReport


class StockDataSerializer(serializers.ModelSerializer):
    """Full OHLCV record serializer."""
    change = serializers.FloatField(read_only=True)
    change_percent = serializers.FloatField(read_only=True)

    class Meta:
        model = StockData
        fields = [
            'symbol', 'date', 'open', 'high', 'low', 'close',
            'volume', 'category', 'change', 'change_percent',
        ]


class StockSymbolSerializer(serializers.Serializer):
    """Summary info for each stock symbol."""
    symbol = serializers.CharField()
    category = serializers.CharField()
    latest_date = serializers.DateField()
    latest_close = serializers.FloatField()
    total_records = serializers.IntegerField()


class CalendarEventSerializer(serializers.ModelSerializer):
    """Serializer for Calendar Events."""
    class Meta:
        model = CalendarEvent
        fields = '__all__'


class QuarterlyReportSerializer(serializers.ModelSerializer):
    """Serializer for Quarterly Earnings Reports."""
    class Meta:
        model = QuarterlyReport
        fields = '__all__'


