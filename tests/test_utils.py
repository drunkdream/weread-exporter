
from weread_exporter import utils

def test_wr_hash():
    assert utils.wr_hash("42557145") == "f343248072895ed9f34f408"
    assert utils.wr_hash("14") == "aab325601eaab3238922e53"
