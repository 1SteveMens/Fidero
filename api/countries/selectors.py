from .models import Country


def by_code(code: str) -> Country:
    return Country.objects.get(code=code.upper())


def config(country: Country | str, key: str, default=None):
    c = by_code(country) if isinstance(country, str) else country
    data = c.config()
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data
