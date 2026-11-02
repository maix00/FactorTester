"""Only identity's HTTP service joins the execution control network."""
from pathlib import Path
import yaml


def test_execution_override_keeps_database_and_ports_private():
    root=Path(__file__).resolve().parents[2]
    value=yaml.safe_load((root/'deploy/docker/keycloak/compose.execution-control.yaml').read_text())
    assert set(value['services'])=={'keycloak'}
    assert value['services']['keycloak']=={'networks':{'execution-control':{'aliases':['tr-keycloak']}}}
    assert value['networks']['execution-control']['external'] is True
    assert ':?' in value['networks']['execution-control']['name']
