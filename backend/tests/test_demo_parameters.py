import openpyxl
import pytest
from app.demo_parameters import generate, main
from app.routes.params import _parse_products, _parse_chips


def test_parser_roundtrip(tmp_path):
    path = tmp_path / 'demo.xlsx'
    generate(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        products = _parse_products(wb['东北欧产品参数表'])
        chips = _parse_chips(wb['芯片天梯图'])
        assert wb['DEMO_NOTICE']['A1'].value.startswith('All names')
    finally:
        wb.close()
    assert [p['product'] for p in products] == ['Demo One', 'Demo Plus']
    assert products[0]['chip_name'] == 'Demo Chip A'
    assert products[0]['price_eur'] == 250
    assert products[1]['wireless_charging_w'] == 15
    assert products[0]['official_url'] == 'https://example.com/demo-one'
    assert [c['chip_name'] for c in chips] == ['Demo Chip B', 'Demo Chip C', 'Demo Chip A']
    assert [c['in_use'] for c in chips] == [True, False, True]
    assert [c['score'] for c in chips] == [200, 200, 100]


def test_existing_file_preserved(tmp_path):
    path = tmp_path / 'existing.xlsx'
    path.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        generate(path)
    assert path.read_bytes() == b'keep'


def test_symlink_preserved(tmp_path):
    original = tmp_path / 'original'
    original.write_bytes(b'keep')
    link = tmp_path / 'link.xlsx'
    link.symlink_to(original)
    with pytest.raises(FileExistsError):
        generate(link)
    assert original.read_bytes() == b'keep'


def test_cli(tmp_path, capsys):
    path = tmp_path / 'demo.xlsx'
    assert main([str(path)]) == 0
    assert '2 products, 3 chips' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main([str(path)])
    assert error.value.code == 2
    assert str(tmp_path) not in capsys.readouterr().err


@pytest.mark.parametrize('name', ['demo.csv', 'missing/demo.xlsx'])
def test_invalid_destination(tmp_path, name):
    with pytest.raises((ValueError, FileNotFoundError)):
        generate(tmp_path / name)
    assert not (tmp_path / name).exists()
