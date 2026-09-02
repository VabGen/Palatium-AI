import { Toaster } from 'react-hot-toast';
import { ChatShell } from './components/ChatShell';

function App() {
  return (
    <>
      <ChatShell />
      <Toaster position="bottom-right" toastOptions={{ duration: 3000 }} />
    </>
  );
}

export default App;
