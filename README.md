# DISCLAIMERS

USE OF THE SMART CONTRACTS AND CODE CONTAINED HEREIN ARE RESTRICTED TO NON-US CITIZENS RESIDING OUTSIDE THE UNITED STATES. THESE SMART CONTRACTS
AND CODE ARE BEING PROVIDED AS IS. No guarantee, representation or warranty is being made, express or implied, as to the safety or correctness
of the user interface or the smart contracts and code. Users may experience delays, failures, errors, omissions or loss of transmitted
information. THE SMART CONTRACTS AND CODE CONTAINED HEREIN ARE PROVIDED AS IS, WHERE IS, WITH ALL FAULTS AND WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING ANY WARRANTY OF MERCHANTABILITY, NON-INFRINGEMENT OR FITNESS FOR ANY PARTICULAR PURPOSE. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SMART CONTRACTS AND CODE OR THE USE OR OTHER DEALINGS IN THE SMART CONTRACTS AND CODE, EVEN IF ADVISED OF
THE POSSIBILITY OF SUCH DAMAGE. Any use of any of the smart contracts and code may be restricted or prohibited under applicable law, including
securities laws, and it is therefore strongly advised for you to contact a reputable attorney in any jurisdiction where these smart contracts
and code may be accessible for any questions or concerns with respect thereto. No information provided herein should be construed as investment
advice or legal advice for any particular facts or circumstances and is not meant to replace competent counsel. Dinari, Inc. is not liable for
any use of the foregoing, and users should proceed with caution and use at their own risk.

Under no circumstances should the smart contracts or the code contained therein be construed as an offer soliciting the purchase or sale of any
security sponsored, discussed, or mentioned by Dinari, Inc., or its personnel. Under no circumstances should the smart contracts or the code
contained therein be construed as a solicitation to purchase any securities or an offer to provide investment advisory services. Any such offer
will only be made separately by means of the confidential offering documents to be read in their entirety, and only to those who, among other
requirements, meet certain qualifications under relevant securities laws that are generally deemed capable of evaluating the merits and risks of
prospective investments and financial matters.

---

# arbitrage-example

Python example for arbitraging between Dinari and Uniswap-based DeFi pools

# Setup

## Environment

1. Install [pyenv](https://github.com/pyenv/pyenv)
2. Run the following to set up a Python environment:
   ```shell
   pyenv install $(pyenv local)
   pip install poetry
   poetry install
   ```

## Application

1. Copy `.env.example` to `.env`
2. Update entries in `.env` to reflect individual's secrets
3. Once the `.env` file is updated, double-check the values are correct by running:
   ```shell
   poetry run python -m arbitrage.cli verify-setup
   ```

### Env Variables

| Variable                  | Notes                                                                        |
|:--------------------------|:-----------------------------------------------------------------------------|
| ARB_PROVIDER_URI          | URI for node provider, such as Alchemy, Quicknode, Infura, etc               |
| ARB_WALLET_MNEMONIC       | Mnemonic for wallet that is operating these examples                         |
| ARB_WALLET_PATH           | Path to use for operating examples                                           |
| ARB_POLYGON_API_KEY       | [Polygon](https://polygon.io/) key to use for scraping stock information     |
| ARB_DSHARE_TICKER_SYMBOL  | Ticker that will be arbitraged (ex. COIN for Coinbase, TSLA for Tesla, etc)  |

# Running

## Pre-requisite

1. To enable trading on Dinari, the owner of the wallet must [register the wallet on Dinari](https://sbt.dinari.com/)
2. A Web3 node provider is required. Some suggestions are [Alchemy](https://www.alchemy.com/), [Infura](https://www.infura.io/),
   and [QuickNode](https://www.quicknode.com/). Remember to sign up for Arbitrum as that is the only chain currently supported
3. To simplify getting stock prices, this example uses [Polygon](https://polygon.io/) as a provider. We recommend the `Advanced` plan as it
   provides real-time data.
4. Since arbitrage operations require converting a dShare to its wrapped version, an approval for unlimited must be made ahead of time to
   reduce fees. To do so, run the following:
   ```shell
   poetry run python -m arbitrage.cli setup-approval-for-wrapping
   ```

## Dinari <> Camelot

This example provides a straightforward arbitrage between Dinari and Camelot. When the prices between Dinari and Camelot drift by a certain
percentage, the bot will buy from the exchange that has a lower price and sell on the other at a higher price.

Instructions to run this example is below:

1. Before running an arbitrage between Dinari and Camelot, check the configurable settings:
   ```shell
   python -m arbitrage.cli camelot --help
   ```
2. After determining configurations, do a dry-run:
   ```shell
   python -m arbitrage.cli camelot {configuration settings} --is-dry-run
   ```
3. If the dry run looks good, proceed to run:
   ```shell
   python -m arbitrage.cli camelot {configuration settings}
   ```
