import { defineFacet, Http, chatRoutes } from "@lumencafe/app/v1";

// 对话应用插件（第 1 批）：路由逻辑在 src/api/chat.mjs（进程基础代码）
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: chatRoutes() });
});
