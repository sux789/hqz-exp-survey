import math
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, digits=3):
    quantum = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def unit_volume(params, dbh, height):
    if height is None or height <= 0:
        return 0.0
    value = params["a"] * (dbh ** params["b"]) * (height ** params["c"])
    return round_half_up(value, params.get("digits", 3))


def diameter_volume(params, dbh, height, count):
    if not count:
        return 0.0
    return round_half_up(unit_volume(params, dbh, height) * count, 3)


def cutting_volume(params, count):
    if not count:
        return 0.0
    return params["a"] * (count ** params["exponent"])


def calculate_summary(survey, schema, visible_species):
    trees = survey.get("trees", {})
    cut = survey.get("cut", {})
    species_totals = {}
    plot_count = 0
    weighted_dbh_squares = 0.0
    total_volume = 0.0

    for name in visible_species:
        params = schema["species"][name]
        rows = trees.get(name, {})
        count = 0
        volume = 0.0
        for dbh in schema["diameters"]:
            key = str(dbh)
            values = rows.get(key, {})
            row_count = int(values.get("count") or 0)
            height = values.get("height")
            row_volume = diameter_volume(params, dbh, height, row_count)
            count += row_count
            volume += row_volume
            plot_count += row_count
            weighted_dbh_squares += row_count * dbh * dbh
        volume = round_half_up(volume, 3)
        total_volume += volume
        species_totals[name] = {"count": count, "volume": volume}

    cut_count = 0
    cut_volume = 0.0
    for dbh in schema["diameters"]:
        count = int(cut.get(str(dbh)) or 0)
        cut_count += count
        cut_volume += cutting_volume(schema["cut"], count)

    factor = schema.get("area_factor", 15.0)
    return {
        "species": species_totals,
        "plot_count": plot_count,
        "average_dbh": math.sqrt(weighted_dbh_squares / plot_count) if plot_count else 0.0,
        "total_volume": round_half_up(total_volume, 3),
        "per_hectare_count": round_half_up(plot_count * factor, 3),
        "per_hectare_volume": round_half_up(total_volume * factor, 3),
        "cut_count": cut_count,
        "cut_volume": round_half_up(cut_volume, 3),
    }


def haversine_distance(points):
    distance = 0.0
    for previous, current in zip(points, points[1:]):
        lat1, lon1 = math.radians(previous["lat"]), math.radians(previous["lng"])
        lat2, lon2 = math.radians(current["lat"]), math.radians(current["lng"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance += 6371000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
    return distance
