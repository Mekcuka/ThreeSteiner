from network_planner.geo.projection import LocalProjection


def test_roundtrip_projection():
    proj = LocalProjection.from_points([37.6, 37.62], [55.75, 55.76])
    x, y = proj.to_local(37.61, 55.755)
    lon, lat = proj.to_wgs84(x, y)
    assert abs(lon - 37.61) < 1e-7
    assert abs(lat - 55.755) < 1e-7
