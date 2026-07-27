import { useState, type FormEvent } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1/passport/extract'

type ValidationResult = {
  mrz_checksum_valid: boolean
  dates_valid: boolean
  errors: string[]
  warnings: string[]
}

type ExtractResult = {
  surname: string | null
  given_name: string | null
  date_of_birth: string | null
  date_of_issue: string | null
  date_of_expiry: string | null
  validation: ValidationResult
}

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ExtractResult | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)

    if (!file) {
      setError('Please choose a JPG, PNG, or PDF file.')
      return
    }

    const formData = new FormData()
    formData.append('file', file)

    setLoading(true)
    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        body: formData,
      })

      const data = await res.json().catch(() => null)
      if (!res.ok) {
        const detail =
          typeof data?.detail === 'string'
            ? data.detail
            : Array.isArray(data?.detail)
              ? data.detail.map((d: { msg?: string }) => d.msg).join(', ')
              : `Request failed (${res.status})`
        throw new Error(detail)
      }

      setResult(data as ExtractResult)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <header className="header">
        <h1>Passport OCR</h1>
        <p>Upload a passport image (JPG/PNG/PDF) to extract identity fields via MRZ + OCR.</p>
      </header>

      <form className="upload-form" onSubmit={onSubmit}>
        <label className="file-label">
          <span>Passport file</span>
          <input
            type="file"
            accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? 'Extracting…' : 'Extract'}
        </button>
      </form>

      {error && <div className="banner error">{error}</div>}

      {result && (
        <section className="results">
          <h2>Extracted fields</h2>
          <table>
            <tbody>
              <tr>
                <th>Surname</th>
                <td>{result.surname ?? '—'}</td>
              </tr>
              <tr>
                <th>Given name</th>
                <td>{result.given_name ?? '—'}</td>
              </tr>
              <tr>
                <th>Date of birth</th>
                <td>{result.date_of_birth ?? '—'}</td>
              </tr>
              <tr>
                <th>Date of issue</th>
                <td>{result.date_of_issue ?? '—'}</td>
              </tr>
              <tr>
                <th>Date of expiry</th>
                <td>{result.date_of_expiry ?? '—'}</td>
              </tr>
            </tbody>
          </table>

          <h2>Validation</h2>
          <ul className="validation">
            <li>
              MRZ checksum:{' '}
              <strong className={result.validation.mrz_checksum_valid ? 'ok' : 'bad'}>
                {result.validation.mrz_checksum_valid ? 'valid' : 'invalid'}
              </strong>
            </li>
            <li>
              Dates:{' '}
              <strong className={result.validation.dates_valid ? 'ok' : 'bad'}>
                {result.validation.dates_valid ? 'valid' : 'invalid'}
              </strong>
            </li>
          </ul>

          {result.validation.errors.length > 0 && (
            <div className="banner error">
              <strong>Errors</strong>
              <ul>
                {result.validation.errors.map((msg) => (
                  <li key={msg}>{msg}</li>
                ))}
              </ul>
            </div>
          )}

          {result.validation.warnings.length > 0 && (
            <div className="banner warn">
              <strong>Warnings</strong>
              <ul>
                {result.validation.warnings.map((msg) => (
                  <li key={msg}>{msg}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

export default App
