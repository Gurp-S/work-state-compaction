import { createRequire, registerHooks } from 'node:module'
import { pathToFileURL } from 'node:url'

const requireHost = createRequire('E:/nodejs/node_modules/@deepseek-ai/dsh/package.json')
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context) }
  catch (error) {
    if (!specifier.startsWith('@deepseek-ai/')) throw error
    return next(pathToFileURL(requireHost.resolve(specifier)).href, context)
  }
} })
