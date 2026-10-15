import { Config } from '@remotion/cli/config'

// Frames are JPEGs of 3200x1800 captures, downscaled on the slab; a quality JPEG intermediate keeps text crisp.
Config.setVideoImageFormat('jpeg')
Config.setJpegQuality(95)
Config.setChromiumOpenGlRenderer('angle')
Config.setBrowserExecutable('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
Config.setChromeMode('chrome-for-testing')
