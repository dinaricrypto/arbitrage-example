from dataclasses import dataclass

from .. import Chain


@dataclass
class CamelotAddress:
    router_address: str
    quoter_address: str


CAMELOT_ADDRESSES: dict[Chain, CamelotAddress] = {
    Chain.ARBITRUM: CamelotAddress(
        router_address="0x1F721E2E82F6676FCE4eA07A5958cF098D339e18",
        quoter_address="0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E",
    )
}
