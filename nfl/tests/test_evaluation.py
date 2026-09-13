from nfl.model.evaluation import regression_metrics


def test_regression_metrics() -> None:
    m = regression_metrics([10, 20, 30], [8, 22, 28])
    assert m.n == 3
    assert round(m.mae, 6) == 2.0
    assert round(m.rmse, 6) == 2.0
    assert round(m.bias, 6) == round(2 / 3, 6)
