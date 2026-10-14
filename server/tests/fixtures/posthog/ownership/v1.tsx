import React, { useMemo } from 'react'

interface BaseFeature {
    feature: string
    owner: string[]
    notes?: React.ReactNode
    label?: string | string[] | false
}

const FEATURE_DATA: Record<string, BaseFeature> = {
    actions: {
        feature: 'Actions',
        owner: ['analytics-platform'],
    },
    alerts: {
        feature: 'Alerts',
        owner: ['analytics-platform'],
    },
    notebooks: {
        feature: 'Notebooks',
        notes: (
            <>
               Owns the notebooks feature and triages other tickets out to the right owner (e.g. insights in notebooks is owned by product analytics)
            </>
        ),
        owner: ['platform-features'],
        label: 'feature/notebooks',
    },
}
