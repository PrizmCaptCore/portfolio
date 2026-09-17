'use client';

import { useEffect } from 'react';
import { motion } from 'framer-motion';
import Analytics from '@/lib/analytics';
import { UpcomingMeetings } from '@/components/Calendar/UpcomingMeetings';

export default function Home() {
  useEffect(() => {
    Analytics.trackPageView('home');
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex h-full min-h-0 flex-col"
    >
      <UpcomingMeetings />
    </motion.div>
  );
}
