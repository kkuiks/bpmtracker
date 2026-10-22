from pathlib import Path
import json
CONFIG = json.loads((Path(__file__).parent / "parameters.json").read_text())
