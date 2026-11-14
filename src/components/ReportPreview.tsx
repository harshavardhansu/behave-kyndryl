import { useEffect, useState } from 'react'
import { Download, FileText } from 'lucide-react'
import { useWorkspace } from '../context'
import { downloadBlob } from '../lib/api'
import { errorMessage } from '../lib/format'
import { Button, Modal } from './ui'

/**
 * "Incident report" button: shows the PDF report in a preview first, then lets the person download it.
 * The report is the shareable document (PDF), not a raw data export.
 */
export function IncidentReportButton({ incidentId, label = 'Incident report' }: { incidentId?: string; label?: string }) {
  const { notify } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !incidentId) return
    let cancelled = false
    let created = ''
    downloadBlob(`/incidents/${incidentId}/resolution-report/pdf`)
      .then((blob) => {
        if (cancelled) return
        created = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
        setUrl(created)
      })
      .catch((problem) => {
        if (!cancelled) setError(errorMessage(problem))
      })
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
      setUrl('')
      setError('')
    }
  }, [open, incidentId])

  function download() {
    if (!url || !incidentId) return
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${incidentId}-incident-report.pdf`
    anchor.click()
    notify('Incident report (PDF) downloaded.')
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} disabled={!incidentId}>
        <FileText size={15} />
        {label}
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Incident report · ${incidentId ?? ''}`}
        description="Preview of the PDF report. Check it, then download it to share."
        wide
        className="report-preview-modal"
      >
        <div className="report-preview" aria-busy={!url && !error}>
          {error ? (
            <p className="report-preview-note" role="alert">The report could not be created: {error}</p>
          ) : url ? (
            <iframe src={`${url}#view=FitH`} title={`Incident report ${incidentId}`} />
          ) : (
            <p className="report-preview-note">Creating the report…</p>
          )}
        </div>
        <div className="modal-footer">
          <Button onClick={() => setOpen(false)}>Close</Button>
          <Button variant="primary" onClick={download} disabled={!url}>
            <Download size={15} />
            Download PDF
          </Button>
        </div>
      </Modal>
    </>
  )
}
