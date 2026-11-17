import { useEffect } from 'react';

export function Login() {
  useEffect(() => {
    window.location.replace('/kdsiginin');
  }, []);
  return null;
}
