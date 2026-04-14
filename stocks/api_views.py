"""
REST API views for NEPSE stock data.
"""
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Max, Min, Count, F, Subquery, OuterRef
from .models import StockData
from .serializers import StockDataSerializer, StockSymbolSerializer


@api_view(['GET'])
def api_overview(request):
    """API root — shows available endpoints."""
    return Response({
        "message": "NEPSE Data API — Free Nepal Stock Exchange Data",
        "version": "1.0",
        "endpoints": {
            "stocks": "/api/stocks/",
            "stock_detail": "/api/stocks/{SYMBOL}/",
            "stock_latest": "/api/stocks/{SYMBOL}/latest/",
            "all_latest": "/api/latest/",
            "nepse_index": "/api/index/",
        },
        "docs": "https://github.com/chydeepak7/nepse_data_api",
    })


@api_view(['GET'])
def stock_list(request):
    """
    List all available stock symbols with summary info.
    GET /api/stocks/
    """
    # Get unique symbols with their latest data
    symbols = (
        StockData.objects
        .values('symbol', 'category')
        .annotate(
            latest_date=Max('date'),
            total_records=Count('id'),
        )
        .order_by('symbol')
    )

    # Get latest close price for each symbol
    results = []
    for s in symbols:
        latest = StockData.objects.filter(
            symbol=s['symbol'], date=s['latest_date']
        ).first()
        results.append({
            'symbol': s['symbol'],
            'category': s['category'],
            'latest_date': s['latest_date'],
            'latest_close': latest.close if latest else 0,
            'total_records': s['total_records'],
        })

    serializer = StockSymbolSerializer(results, many=True)
    return Response({
        "count": len(results),
        "results": serializer.data,
    })


class StockHistoryView(generics.ListAPIView):
    """
    Get historical OHLCV data for a specific stock.
    GET /api/stocks/{SYMBOL}/
    Query params: ?from=YYYY-MM-DD&to=YYYY-MM-DD
    """
    serializer_class = StockDataSerializer

    def get_queryset(self):
        symbol = self.kwargs['symbol'].upper()
        qs = StockData.objects.filter(symbol=symbol).order_by('-date')

        date_from = self.request.query_params.get('from')
        date_to = self.request.query_params.get('to')

        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        return qs


@api_view(['GET'])
def stock_latest(request, symbol):
    """
    Get the latest price for a specific stock.
    GET /api/stocks/{SYMBOL}/latest/
    """
    symbol = symbol.upper()
    latest = StockData.objects.filter(symbol=symbol).order_by('-date').first()

    if not latest:
        return Response(
            {"error": f"No data found for {symbol}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = StockDataSerializer(latest)
    return Response(serializer.data)


@api_view(['GET'])
def all_latest(request):
    """
    Get the latest price for all stocks.
    GET /api/latest/
    """
    # Find the most recent trading date
    latest_date = StockData.objects.aggregate(Max('date'))['date__max']

    if not latest_date:
        return Response({"results": [], "date": None})

    records = StockData.objects.filter(date=latest_date).order_by('symbol')
    serializer = StockDataSerializer(records, many=True)

    return Response({
        "date": latest_date,
        "count": records.count(),
        "results": serializer.data,
    })


@api_view(['GET'])
def nepse_index(request):
    """
    Get NEPSE index data.
    GET /api/index/
    Query params: ?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=30
    """
    qs = StockData.objects.filter(symbol='NEPSE').order_by('-date')

    date_from = request.query_params.get('from')
    date_to = request.query_params.get('to')
    limit = request.query_params.get('limit', 30)

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 30

    qs = qs[:limit]
    serializer = StockDataSerializer(qs, many=True)

    return Response({
        "symbol": "NEPSE",
        "count": len(serializer.data),
        "results": serializer.data,
    })


from .models import CalendarEvent, QuarterlyReport
from .serializers import CalendarEventSerializer, QuarterlyReportSerializer

class CalendarEventListView(generics.ListAPIView):
    """
    Get NepseAlpha calendar events.
    GET /api/calendar/events/
    """
    queryset = CalendarEvent.objects.all()
    serializer_class = CalendarEventSerializer


class QuarterlyReportListView(generics.ListAPIView):
    """
    Get Quarterly Earnings Reports.
    GET /api/calendar/reports/
    """
    queryset = QuarterlyReport.objects.all()
    serializer_class = QuarterlyReportSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        symbol = self.request.query_params.get('symbol')
        if symbol:
            qs = qs.filter(symbol=symbol.upper())
        return qs


import threading
from django.conf import settings
from django.core.management import call_command

@api_view(['GET'])
def ping(request):
    """
    Simple endpoint to wake up the server (Render free tier).
    GET /api/ping/
    """
    return Response({"status": "awake", "message": "Server is up and running!"})


@api_view(['POST'])
def trigger_scrape(request):
    """
    Endpoint to trigger background scraping via cron-job.org.
    Requires CRON_SECRET_KEY in the Authorization header.
    POST /api/trigger-scrape/
    """
    auth_header = request.headers.get("Authorization")
    expected_token = getattr(settings, 'CRON_SECRET_KEY', None)

    if not auth_header or auth_header != f"Bearer {expected_token}":
        return Response(
            {"error": "Unauthorized. Invalid or missing secret key."},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Run in a background thread so the API returns quickly before Render/cron-job times out
    def background_scrape():
        try:
            print("Background scrape triggered via API...")
            call_command("scrape")
            
            # Run weekly tasks too if requested (e.g. ?full=1)
            # Actually, easiest is just to run the calendar scrapes too
            # but standard daily scrape should suffice for the main functionality
        except Exception as e:
            print(f"Background scrape failed: {e}")

    thread = threading.Thread(target=background_scrape)
    thread.start()

    return Response({
        "status": "processing",
        "message": "Background scrape has been triggered and is running."
    }, status=status.HTTP_202_ACCEPTED)

