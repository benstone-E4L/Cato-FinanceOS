/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CATO_BUILD_VERSION?: string;
  readonly VITE_CATO_BUILD_SHA?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.png" {
  const src: string;
  export default src;
}
declare module "*.jpg" {
  const src: string;
  export default src;
}
declare module "*.svg" {
  const src: string;
  export default src;
}
