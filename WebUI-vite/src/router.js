import { createRouter, createWebHashHistory } from "vue-router";
import SystemView from "./views/SystemView.vue";
import UsersView from "./views/UsersView.vue";
import ConfigView from "./views/ConfigView.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/system" },
    { path: "/system", component: SystemView },
    { path: "/users", component: UsersView },
    { path: "/config", component: ConfigView },
  ],
});

export default router;
