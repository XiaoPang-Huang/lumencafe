import { defineFacet, Http } from "@lumencafe/app/v1";

// 0A 验收探针：验证「HTTP 默认拒绝」——不带身份的请求应返回 401
export default defineFacet((host, self) => {
  self.contribute(Http, {
    routes: {
      "GET /api/ping": async () => ({
        kind: "json",
        value: { pong: true },
      }),
    },
  });
});
