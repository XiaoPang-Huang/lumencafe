import { defineFacet, Http, papersRoutes, readerRoutes, pushRoutes } from "@lumencafe/app/v1";

// 论文应用插件（第 3、4 批）：库/阅读器/问答 + 订阅与定时推送
export default defineFacet((host, self) => {
  self.contribute(Http, { routes: { ...papersRoutes(), ...readerRoutes(), ...pushRoutes() } });
});
