import { refreshMarketData } from "../services/marketDataService.js";

const main = async (): Promise<void> => {
  const snapshot = await refreshMarketData();
  console.log(
    `Updated ${snapshot.assets.length} assets at ${snapshot.updatedAt} from ${snapshot.source}.`
  );
};

void main();

