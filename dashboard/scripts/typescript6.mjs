// openapi-typescript needs the TypeScript 6 JavaScript API, but the dashboard compiles with
// TypeScript 7, whose package exports no JavaScript API. For the type generator only, resolve
// "typescript" to the official TypeScript 6 API package.
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    return nextResolve(specifier === "typescript" ? "@typescript/typescript6" : specifier, context);
  },
});
