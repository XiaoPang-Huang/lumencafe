import { defineFacet, Http, shellRoutes } from "@lumencafe/app/v1";

// 页面外壳插件（0C）：静态服务逻辑在 src/api/static.mjs（进程基础代码），
// 这里只负责把路由挂进 Http 注册表。
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: shellRoutes() });
});
