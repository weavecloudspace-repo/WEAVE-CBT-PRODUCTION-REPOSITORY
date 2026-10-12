import { useCallback, useEffect, useState } from 'react'

export function useImagePreview() {
  const [image, setImage] = useState({ file: null, url: '' })
  const setFile = useCallback((file) => {
    const url = file && typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
    setImage({ file, url })
  }, [])
  useEffect(() => {
    if (!image.url) return undefined
    return () => URL.revokeObjectURL(image.url)
  }, [image.url])
  return [image.file, image.url, setFile]
}
