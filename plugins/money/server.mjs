import { defineFacet, Http, moneyRoutes } from "@lumencafe/app/v1";

// 记账应用插件（第 2 批）：路由逻辑在 src/api/money.mjs（进程基础代码）
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: moneyRoutes() });
});
