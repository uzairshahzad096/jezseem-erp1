from pydantic import BaseModel


class StatValue(BaseModel):
    """A dashboard figure. `value` is None when the owning module has no
    backend yet — the UI renders an em dash rather than a fabricated zero."""
    value: float | None = None
    formatted: str | None = None
    delta_percent: float | None = None


class ChartSeries(BaseModel):
    name: str
    data: list[float]


class ChartData(BaseModel):
    categories: list[str]
    series: list[ChartSeries]


class ActivityItem(BaseModel):
    id: str
    title: str
    subtitle: str
    status: str  # pending | progress | rejected | done


class DashboardSummary(BaseModel):
    company_name: str
    branch_name: str | None
    financial_year: str | None
    user_full_name: str

    stats: dict[str, StatValue]
    revenue: ChartData | None = None
    sales_statistics: dict[str, ChartData] = {}
    recent_activity: list[ActivityItem] = []
    top_products: list[dict] = []
