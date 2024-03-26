from importlib.resources import files
import json


def get_abi_as_json_from_file_name(abi_file_name: str) -> dict:
    source = files(__package__).joinpath(abi_file_name)
    return json.loads(source.read_text())


CAMELOT_POOL_ABI = get_abi_as_json_from_file_name("camelot_pool.json")
CAMELOT_QUOTER_ABI = get_abi_as_json_from_file_name("camelot_quoter.json")
CAMELOT_ROUTER_ABI = get_abi_as_json_from_file_name("camelot_router.json")
DINARI_ORDER_PROCESSOR_ABI = get_abi_as_json_from_file_name("dinari_order_processor.json")
ERC20_ABI = get_abi_as_json_from_file_name("erc20.json")
DSHARE_ABI = get_abi_as_json_from_file_name("dshare.json")
WRAPPED_DSHARE_ABI = get_abi_as_json_from_file_name("wrapped_dshare.json")
