const setupViews = new Set(['welcome', 'pairing-code', 'server-name', 'pairing', 'paired-success'])
export const isSetupView = (view) => setupViews.has(view)
