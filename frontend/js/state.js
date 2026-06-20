/**
 * Shared DOM references, UI state, refresh intervals, and glossary constants.
 * Loaded first so formatter, renderer, and controller scripts share one state.
 */

const button = document.querySelector("#load-recommendations");
const trendsButton = document.querySelector("#load-trends");
const newsButton = document.querySelector("#load-news");
const summarizeMarketButton = document.querySelector("#summarize-market");
const menuToggle = document.querySelector("#menu-toggle");
const sidebar = document.querySelector("#sidebar");
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
const newsList = document.querySelector("#news-list");
const marketTakeEl = document.querySelector("#market-take-output");
const toggleTrendsButton = document.querySelector("#toggle-trends");
const toggleNewsButton = document.querySelector("#toggle-news");
const toastEl = document.querySelector("#toast");

let currentRecommendationRunId = null;
let companyNames = {};
let candidatePool = [];
let visibleCandidates = [];
let queuedCandidates = [];
let visibleCandidateLimit = 3;
let latestTrends = [];
let latestNews = [];
let showAllTrends = false;
let showAllNews = false;
let priceRefreshIntervalId = null;
let trendMetricRotateIntervalId = null;
let dashboardRefreshIntervalId = null;
let dashboardRequestInFlight = false;
const DEFAULT_TREND_COUNT = 6;
const DEFAULT_NEWS_COUNT = 5;
const PRICE_REFRESH_MS = 15000;
const DASHBOARD_REFRESH_MS = 10000;
const TREND_METRIC_ROTATE_MS = 5000;
const NEUTRAL_TREND_PERCENT_THRESHOLD = 0.2;
const TOAST_TIMEOUT_MS = 5200;
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
