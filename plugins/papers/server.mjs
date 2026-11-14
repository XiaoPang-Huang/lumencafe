import { defineFacet, Http, papersRoutes, readerRoutes } from "@lumencafe/app/v1";

// 论文应用插件（第 3 批）：路由逻辑在 src/api/papers.mjs（库）与 src/api/reader.mjs（阅读器/问答）
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: { ...papersRoutes(), ...readerRoutes() } });
});
