import { useState, useEffect } from 'react';
import { ThemeProvider } from '@/context/ThemeContext';
import { Header } from '@/components/layout/Header';
import { Navigation, TabType } from '@/components/layout/Navigation';
import { ToastProvider } from '@/components/layout/ToastContainer';
import { ProcessingTab } from '@/components/processing/ProcessingTab';
import { GalleryTab } from '@/components/gallery/GalleryTab';
import { ConfigTab } from '@/components/config/ConfigTab';
import { ScheduleTab } from '@/components/schedule/ScheduleTab';

export function AppContent() {
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const hash = window.location.hash.toLowerCase();
    if (hash.includes('gallery')) return 'gallery';
    if (hash.includes('config')) return 'config';
    if (hash.includes('schedule')) return 'schedule';
    return 'processing';
  });

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.toLowerCase();
      if (hash.includes('gallery')) setActiveTab('gallery');
      else if (hash.includes('config')) setActiveTab('config');
      else if (hash.includes('schedule')) setActiveTab('schedule');
      else if (hash.includes('processing')) setActiveTab('processing');
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    if (!window.location.hash.startsWith(`#${tab}`)) {
      window.location.hash = `#${tab}`;
    }
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'processing':
        return <ProcessingTab />;
      case 'gallery':
        return <GalleryTab />;
      case 'config':
        return <ConfigTab />;
      case 'schedule':
        return <ScheduleTab />;
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans antialiased">
      <Header />
      <Navigation activeTab={activeTab} onTabChange={handleTabChange} />
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {renderTabContent()}
      </main>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="exif-tagger-theme">
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
