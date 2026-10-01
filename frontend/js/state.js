/**
 * Shared DOM references, UI state, refresh intervals, and glossary constants.
 * Loaded first so formatter, renderer, and controller scripts share one state.
 */

// DOM elements used by controllers and renderers. Keeping references here avoids repeated querySelector calls across files.
const button = document.querySelector("#load-recommendations");
const strategyTabs = document.querySelectorAll(".strategy-tab");
const strategySubhead = document.querySelector("#strategy-subhead");
const highlightsEl = document.querySelector("#daily-highlights");
const trendsButton = document.querySelector("#load-trends");
const newsButton = document.querySelector("#load-news");
const summarizeMarketButton = document.querySelector("#summarize-market");
const exploreDashboardButton = document.querySelector("#explore-dashboard");
const exploreDashboardSecondaryButton = document.querySelector("#explore-dashboard-secondary");
const closeExploreButton = document.querySelector("#close-explore");
const exploreOverlay = document.querySelector("#explore-overlay");
const authButtons = document.querySelectorAll(".auth-action");
const authStatus = document.querySelector("#auth-status");
const navLinks = document.querySelectorAll(".nav-link");
const panels = document.querySelectorAll(".tab-panel");
const recommendationStatus = document.querySelector("#recommendation-status");
const trendStatus = document.querySelector("#trend-status");
const newsStatus = document.querySelector("#news-status");
const marketTakeStatus = document.querySelector("#market-take-status");
const reviewEl = document.querySelector("#agent-review");
const candidateList = document.querySelector("#candidate-list");
const dashboardEl = document.querySelector("#dashboard");
const trendList = document.querySelector("#trend-list");
const earningsList = document.querySelector("#earnings-list");
const earningsStatus = document.querySelector("#earnings-status");
const toggleEarningsButton = document.querySelector("#toggle-earnings");
const newsList = document.querySelector("#news-list");
const marketTakeEl = document.querySelector("#market-take-output");
const toggleTrendsButton = document.querySelector("#toggle-trends");
const toggleNewsButton = document.querySelector("#toggle-news");
const toastEl = document.querySelector("#toast");

// Mutable UI state shared across the simple script modules. These values track the active recommendation run, visible cards, loaded market data, and refresh timers.
let currentRecommendationRunId = null;
// The strategy the user has selected, and the one the candidates on screen actually came from.
// They differ while a scan is running, so renderers read the second rather than the first.
// The page opens on the day's saved picks; a strategy key only applies once a scan tab is chosen.
const HIGHLIGHTS_TAB = "highlights";
const HIGHLIGHTS_SUBHEAD = "What HELIOS found scanning on its own at the open, midday, and an hour before the close.";
let activeTab = HIGHLIGHTS_TAB;
let activeStrategyKey = "cash_secured_put";
let currentStrategyKey = "cash_secured_put";
// What the unattended scans found today, kept so a re-check can redraw one pick in place.
let latestHighlights = [];
let companyNames = {};
let candidatePool = [];
let recommendedContract = null;
let latestTrends = [];
// The earnings table and the controls that narrow it.
let latestEarnings = [];
let excludedFunds = [];
let earningsFilter = "All";
let earningsSearch = "";
let showAllEarnings = false;
let latestNews = [];
let showAllTrends = false;
let showAllNews = false;
let trendFilter = "All";
let trendSort = "default";
let priceRefreshIntervalId = null;
let dashboardRefreshIntervalId = null;
let dashboardRequestInFlight = false;
// UI sizing, refresh, and formatting constants. These control how much data appears by default and how frequently live sections refresh.
const MAX_ALTERNATES = 3;
const DEFAULT_TREND_COUNT = 12;
// Ticker groups for the Trends page segment filter. Tickers outside every group still appear under "All".
const TREND_CATEGORIES = {
    "ETFs": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLV", "XLE", "XLY"],
    "Mega-tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "AMD", "ORCL", "NFLX", "CSCO", "CRM", "INTC", "MU", "QCOM"],
    "Financials": ["JPM", "V", "MA", "BAC", "C", "WFC", "PYPL", "SOFI", "HOOD"],
    "Consumer": ["COST", "HD", "WMT", "TSLA", "UBER", "DIS", "NKE", "SBUX", "KO", "PEP", "T", "VZ", "SHOP", "RBLX", "SNAP", "PINS", "PLTR", "F", "GM", "CCL", "DAL", "AAL", "UAL"],
};
const DEFAULT_NEWS_COUNT = 5;
const PRICE_REFRESH_MS = 15000;
const DASHBOARD_REFRESH_MS = 10000;
const NEUTRAL_TREND_PERCENT_THRESHOLD = 0.2;
const TOAST_TIMEOUT_MS = 5200;
// Beginner glossary used by AI Market Take hover chips. The terms explain options and macro vocabulary without making the main take overly long.
const GLOSSARY = {
    "assignment risk": "The chance you must buy 100 shares at the strike price if the put is assigned.",
    "cash-secured put": "A put option you sell while keeping enough cash to buy 100 shares if assigned.",
    delta: "A rough estimate of how much the option price moves when the stock moves $1. Lower delta usually means farther from the current stock price.",
    IV: "Implied volatility. Higher IV can mean richer premium, but also more uncertainty.",
    "implied volatility": "The market's estimate of how much the stock may move. Higher usually means higher option prices.",
    spread: "The gap between bid and ask. Tighter spreads usually mean easier entry and exit.",
    premium: "Money received for selling the put contract.",
    "margin of safety": "Extra room between the current stock price and your strike or breakeven price.",
    "support": "A price area where buyers have recently stepped in.",
    "rates": "Interest rates. Higher rates can pressure growth stocks because future earnings become less attractive.",
    inflation: "Rising prices across the economy. It can affect Fed decisions and stock valuations.",
    "Fed": "The Federal Reserve, the U.S. central bank that influences interest rates.",
    "relief rally": "A short bounce after selling pressure, not always a true trend change.",
    "liquid": "Easy to trade because there are enough buyers and sellers.",
    "volatility": "How much and how quickly a stock price moves.",
};
