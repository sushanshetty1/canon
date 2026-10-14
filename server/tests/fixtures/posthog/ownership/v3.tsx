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
        owner: ['product-analytics'],
    },
    alerts: {
        feature: 'Alerts',
        owner: ['product-analytics'],
    },
    notebooks: {
        feature: 'Notebooks',
        owner: ['data-tools'],
        label: 'feature/notebooks',
    },
}
