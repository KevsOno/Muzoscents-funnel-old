import { useEffect } from 'react';

export default function Login() {
  useEffect(() => {
    // If we land on the React login page, instantly bounce to the central system login
    window.location.replace('/kdsiginin');
  }, []);
  return null;
}
